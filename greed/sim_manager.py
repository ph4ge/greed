import logging
import os
import sys
from typing import Callable

from greed import options
from greed.state import SymbolicEVMState

log = logging.getLogger(__name__)


class SimulationManager:
    def __init__(self, entry_state: SymbolicEVMState, project):
        self.project = project
        self._halt = False
        self._techniques = []

        # initialize empty stashes
        self.stashes = {
            'active': [],
            'deadended': [],
            'found': [],
            'pruned': [],
            'unsat': [],
            'errored': []
        }

        self.insns_count = 0
        self.error = list()

        self.active.append(entry_state)

    def set_error(self, s: str):
        log.error(f'[ERROR] {s}')
        self.error += [s]

    @property
    def states(self):
        """
        :return: All the states
        """
        return sum(self.stashes.values(), [])

    @property
    def active(self):
        """
        :return: Active stash
        """
        return self.stashes['active']

    @property
    def deadended(self):
        """
        :return: Deadended stash
        """
        return self.stashes['deadended']

    @property
    def found(self):
        """
        :return: Found stash
        """
        return self.stashes['found']

    @property
    def one_active(self):
        """
        :return: First element of the active stash, or None if the stash is empty
        """
        if len(self.stashes['active']) > 0:
            return self.stashes['active'][0]
        else:
            return None

    @property
    def one_deadended(self):
        """
        :return: First element of the deadended stash, or None if the stash is empty
        """
        if len(self.stashes['deadended']) > 0:
            return self.stashes['deadended'][0]
        else:
            return None

    @property
    def one_found(self):
        """
        :return: First element of the found stash, or None if the stash is empty
        """
        if len(self.stashes['found']) > 0:
            return self.stashes['found'][0]
        else:
            return None

    def use_technique(self, technique: "ExplorationTechnique"):
        technique.project = self.project
        technique.setup(self)
        self._techniques.append(technique)
        return technique

    def move(self, from_stash: str, to_stash: str, filter_func: Callable[[SymbolicEVMState], bool] = lambda s: True):
        """
        Move all the states that meet the filter_func condition from from_stash to to_stash
        :param from_stash: Source stash
        :param to_stash: Destination Stash
        :param filter_func: A function that discriminates what states should be moved
        :return: None
        """
        for s in list(self.stashes[from_stash]):
            if filter_func(s):
                self.stashes[from_stash].remove(s)
                self.stashes[to_stash].append(s)

    def step(self, find: Callable[[SymbolicEVMState], bool] = lambda s: False,
                   prune: Callable[[SymbolicEVMState], bool] = lambda s: False):
        log.debug('-' * 30)
        new_active = list()
        # Let the techniques manipulate the stashes
        for tech in self._techniques: 
            self.stashes = tech.check_stashes(self, self.stashes)
        
        # Let's step the active!
        for state in self.active:
            successors = self.single_step_state(state)
            new_active += successors
        
        self.stashes['active'] = new_active

        self.insns_count += 1

        self.move(from_stash='active', to_stash='found', filter_func=find)
        self.move(from_stash='active', to_stash='errored', filter_func=lambda s: s.error != None)
        self.move(from_stash='active', to_stash='deadended', filter_func=lambda s: s.halt)
        self.move(from_stash='active', to_stash='pruned', filter_func=prune)

        if not options.LAZY_SOLVES:
            self.move(from_stash='active', to_stash='unsat', filter_func=lambda s: not s.solver.is_sat())        
        self.move(from_stash='found', to_stash='unsat', filter_func=lambda s: not s.solver.is_sat())

        for s in self.stashes['pruned'] + self.stashes['unsat'] + self.stashes['errored']:
            s.solver.dispose_context()

    def single_step_state(self, state: SymbolicEVMState):
        log.debug(f"Stepping {state}")
        log.debug(state.curr_stmt)

        # state.solver.simplify()

        # Some inspect capabilities, uses the plugin.
        if hasattr(state, "inspect"):
            # Trigger breakpoints on specific stmt_id
            if state.pc in state.inspect.breakpoints_stmt_ids.keys():
                state.inspect.breakpoints_stmt_ids[state.pc](self, state)
            # Trigger breakpoints on all the stmt with that name
            if state.curr_stmt.__internal_name__ in state.inspect.breakpoints_stmt.keys():
                state.inspect.breakpoints_stmt[state.curr_stmt.__internal_name__](self, state)
        successors = list()
        
        # Let exploration techniques manipulate the state
        # that is going to be handled
        state_to_step = state
        for t in self._techniques: 
            state_to_step = t.check_state(self, state_to_step)

        # Finally step the state
        try:
            successors += state.curr_stmt.handle(state)
        except Exception as e:
            log.exception(f"Something went wrong while generating successor for {state}")
            state.error = e
            state.halt = True
            successors += [state]
            #from web3 import Web3
            #w3 = Web3()
            #checksummed_address = w3.toChecksumAddress(hex(bv_unsigned_value(state.ctx["ADDRESS"])))
            #for t in self._techniques:
            #    if hasattr(t, "_target_stmt"):
            #        target_pc = t._target_stmt.id
            #        break
            #send_to_hackcess_bot(f"{checksummed_address} : {state.error.args[0]} | target {target_pc}")

        # Let exploration techniques manipulate the successors
        for t in self._techniques: 
            successors = t.check_successors(self, successors)
        
        return successors

    def run(self, find: Callable[[SymbolicEVMState], bool] = lambda s: False,
            prune: Callable[[SymbolicEVMState], bool] = lambda s: False,
            find_all=False):
        """
        Run the simulation manager, until the `find` condition is met. 
        The analysis will stop when there are no more active states, some states met the `find` condition 
        (these will be moved to the found stash), or the exploration techniques are done.
        If no ET are plugged, the default searching strategy is BFS.
        When techniques are plugged, their methods are executed following the same order they were plugged.
        
        e.g., assuming we have T1 and T2.
                T1(check_stashes) -> T2(check_stashes) -> T1(check_state) -> T2(check_state) 
                    -> T1(check_successors) -> T2(check_successors)

        :param find: Function that will be called after each step. The matching states will be moved to the found stash
        :param prune: Function that will be called after each step. The matching states will be moved to the pruned stash
        :return: None
        """
        try:
            # We iterate until we have active states, 
            # OR, if any of the ET is not done.
            while len(self.active) > 0 or (self._techniques != [] and 
                                            not(all([t.is_complete(self) for t in self._techniques]))):
                
                if len(self.found) > 0 and not find_all:
                    break
                elif self._halt:
                    break
                
                self.step(find, prune)

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]

            log.exception(f'Exception while stepping the Simulation Manager')
            self.set_error(f'{exc_type.__name__} at {fname}:{exc_tb.tb_lineno}')
            sys.exit(1)


    def __str__(self):
        stashes_str = [f'{len(stash)} {stash_name}'  # {[s for s in stash]}'
                       for stash_name, stash in self.stashes.items() if len(stash)]
        errored_count = len([s for s in self.states if s.error])
        stashes_str += [f'({errored_count} errored)']
        reverted_count = len([s for s in self.states if s.revert])
        stashes_str += [f'({reverted_count} reverted)']
        return f'<SimulationManager[{self.insns_count}] with {", ".join(stashes_str)}>'

    def __repr__(self):
        return self.__str__()
