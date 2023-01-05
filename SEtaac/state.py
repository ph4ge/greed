import datetime
import logging

from SEtaac import options as opt
from SEtaac.memory import LambdaMemory, PartialConcreteStorage
from SEtaac.solver.shortcuts import *
from SEtaac.state_plugins import SimStatePlugin, SimStateSolver, SimStateGlobals, SimStateInspect
from SEtaac.utils.exceptions import VMNoSuccessors, VMUnexpectedSuccessors
from SEtaac.utils.exceptions import VMSymbolicError
from SEtaac.utils.extra import UUIDGenerator

log = logging.getLogger(__name__)


class SymbolicEVMState:
    uuid_generator = UUIDGenerator()

    def __init__(self, xid, project, partial_init=False, init_ctx=None, options=None, max_calldatasize=None, partial_concrete_storage=False):
        self.xid = xid
        self.project = project
        self.code = project.code
        self.uuid = SymbolicEVMState.uuid_generator.next()

        if partial_init:
            # this is only used when copying the state
            return
    
        # Register default plugins
        self.active_plugins = dict()
        self._register_default_plugins()
        self._pc = None
        self.trace = list()
        self.memory = LambdaMemory(tag=f"MEMORY_{self.xid}", value_sort=BVSort(8), default=BVV(0, 8), state=self)

        # We want every state to have an individual set
        # of options.
        self.options = options or dict()            
        self.registers = dict()
        self.ctx = dict()
        self.callstack = list()
        self.returndata = {'size': None, 'instruction_count': None}
        self.instruction_count = 0
        self.halt = False
        self.revert = False
        self.error = None
        self.gas = BVS(f'GAS_{self.xid}', 256)
        self.start_balance = BVS(f'BALANCE_{self.xid}', 256)
        self.balance = BV_Add(self.start_balance, ctx_or_symbolic('CALLVALUE', self.ctx, self.xid))
        self.ctx['CODESIZE-ADDRESS'] = BVV(len(self.code), 256)
        self.sha_observed = list()

        # make sure we can exploit it in the foreseeable future
        self.min_timestamp = (datetime.datetime(2022, 1, 1) - datetime.datetime(1970, 1, 1)).total_seconds()
        self.max_timestamp = (datetime.datetime.now() - datetime.datetime(1970, 1, 1)).total_seconds()
        self.MAX_CALLDATA_SIZE = max_calldatasize or opt.MAX_CALLDATA_SIZE

        self.calldata = None
        self.calldatasize = None

        # Apply init context to the state
        self.set_init_ctx(init_ctx)

        if not partial_concrete_storage:
            # Fully symbolic storage
            self.storage = LambdaMemory(tag=f"STORAGE_{self.xid}", value_sort=BVSort(256), state=self)
        else:
            log.debug("Using PartialConcreteStorage")
            self.storage = PartialConcreteStorage(tag=f"PCONCR_STORAGE_{self.xid}", value_sort=BVSort(256), state=self)

    def set_init_ctx(self, init_ctx=None):
        init_ctx = init_ctx or dict()
        if "CALLDATA" in init_ctx:
            # We want to give the possibility to specify interleaving of symbolic/concrete data bytes in the CALLDATA.
            # for instance: "CALLDATA" = ["0x1546138954SSSS81923899"]. There are 2 symbolic bytes represented by SSSS.
            assert isinstance(init_ctx['CALLDATA'], str), "Wrong type for CALLDATA initial context"

            # Parse the CALLDATA (divide the input string byte by byte)
            calldata_raw = init_ctx['CALLDATA'].replace("0x", '')
            calldata_bytes = [calldata_raw[i:i + 2] for i in range(0, len(calldata_raw), 2)]

            self.calldatasize = BVS(f'CALLDATASIZE_{self.xid}', 256)

            if "CALLDATASIZE" in init_ctx:
                # CALLDATASIZE is equal than size(CALLDATA), pre-constraining to this exact size
                self.add_constraint(Equal(self.calldatasize, BVV(init_ctx["CALLDATASIZE"], 256)))

                self.calldata = LambdaMemory(tag=f"CALLDATA_{self.xid}", value_sort=BVSort(8), default=BVV(0, 8), state=self)

                assert init_ctx["CALLDATASIZE"] >= len(calldata_bytes), "CALLDATASIZE is smaller than len(CALLDATA)"
                if init_ctx["CALLDATASIZE"] > len(calldata_bytes):
                    # CALLDATASIZE is bigger than size(CALLDATA), we set the unspecified CALLDATA as symbolic
                    for index in range(len(calldata_bytes), init_ctx["CALLDATASIZE"]):
                        self.calldata[BVV(index, 256)] = BVS(f'CALLDATA_BYTE_{index}', 8)

                # If the CALLDATASIZE is fixed, we change the MAX_CALLDATASIZE to that value.                
                self.MAX_CALLDATA_SIZE = self.solver.eval(self.calldatasize)
            else:
                log.debug(f"CALLDATASIZE MIN{len(calldata_bytes)}-MAX{self.MAX_CALLDATA_SIZE + 1}")
                self.calldata = LambdaMemory(tag=f"CALLDATA_{self.xid}", value_sort=BVSort(8), state=self)
                # CALLDATASIZE < MAX_CALLDATA_SIZE
                self.add_constraint(BV_ULT(self.calldatasize, BVV(self.MAX_CALLDATA_SIZE + 1, 256)))
                # CALLDATASIZE is >= than the length of the provided CALLDATA bytes
                self.add_constraint(BV_UGE(self.calldatasize, BVV(len(calldata_bytes), 256)))

            for index, cb in enumerate(calldata_bytes):
                if cb == 'SS':
                    log.debug(f"Storing symbolic byte at index {index} in CALLDATA")
                    # special sequence for symbolic bytes
                    self.calldata[BVV(index, 256)] = BVS(f'CALLDATA_BYTE_{index}', 8)
                else:
                    log.debug("Initializing CALLDATA at {}".format(index))
                    self.calldata[BVV(index, 256)] = BVV(int(cb, 16), 8)
        else:
            self.calldata = LambdaMemory(tag=f"CALLDATA_{self.xid}", value_sort=BVSort(8), state=self)
            # We assume fully symbolic CALLDATA and CALLDATASIZE in this case
            self.calldatasize = BVS(f'CALLDATASIZE_{self.xid}', 256)
            # CALLDATASIZE < MAX_CALLDATA_SIZE
            self.add_constraint(BV_ULT(self.calldatasize, BVV(self.MAX_CALLDATA_SIZE + 1, 256)))

        if "CALLER" in init_ctx:
            assert isinstance(init_ctx['CALLER'], str), "Wrong type for CALLER initial context"
            self.ctx["CALLER"] = BVV(int(init_ctx["CALLER"],16), 256)

        if "ORIGIN" in init_ctx:
            assert isinstance(init_ctx['ORIGIN'], str), "Wrong type for ORIGIN initial context"
            self.ctx["ORIGIN"] = BVV(int(init_ctx["ORIGIN"],16), 256)
        
        if "BALANCE" in init_ctx:
            assert isinstance(init_ctx['BALANCE'], int), "Wrong type for BALANCE initial context"
            self.add_constraint(Equal(self.start_balance, BVV(init_ctx['BALANCE'], 256)))
        
        if "ADDRESS" in init_ctx:
            assert isinstance(init_ctx['ADDRESS'], str), "Wrong type for ADDRESS initial context"
            self.ctx["ADDRESS"] = BVV(int(init_ctx["ADDRESS"],16), 256)

        if "NUMBER" in init_ctx:
            assert isinstance(init_ctx['NUMBER'], int), "Wrong type for NUMBER initial context"
            self.ctx["NUMBER"] = BVV(init_ctx["NUMBER"], 256)

        if "DIFFICULTY" in init_ctx:
            assert isinstance(init_ctx['DIFFICULTY'], int), "Wrong type for DIFFICULTY initial context"
            self.ctx["DIFFICULTY"] = BVV(init_ctx["DIFFICULTY"], 256)

        if "TIMESTAMP" in init_ctx:
            assert isinstance(init_ctx['TIMESTAMP'], int), "Wrong type for TIMESTAMP initial context"
            self.ctx["TIMESTAMP"] = BVV(init_ctx["TIMESTAMP"], 256)
        
        if "CALLVALUE" in init_ctx:
            assert isinstance(init_ctx['CALLVALUE'], int), "Wrong type for CALLVALUE initial context"
            self.ctx["CALLVALUE"] = BVV(init_ctx["CALLVALUE"], 256)

    @property
    def pc(self):
        return self._pc

    @property
    def curr_stmt(self):
        return self.project.factory.statement(self._pc)

    @property
    def constraints(self):
        return self.solver.constraints

    @pc.setter
    def pc(self, value):
        self._pc = value

    def set_next_pc(self):
        try:
            curr_bb = self.project.factory.block(self.curr_stmt.block_id)
            stmt_list_idx = curr_bb.statements.index(self.curr_stmt)
            remaining_stmts = curr_bb.statements[stmt_list_idx + 1:]
            if remaining_stmts:
                self.pc = remaining_stmts[0].id
            else:
                self.pc = self.get_fallthrough_pc()
        except VMNoSuccessors:
            self.halt = True
        except VMUnexpectedSuccessors:
            self.halt = True

    def get_fallthrough_pc(self):
        curr_bb = self.project.factory.block(self.curr_stmt.block_id)

        if len(curr_bb.succ) == 0:
            #  case 1: end of the block and no targets
            log.debug("Next stmt is NONE")
            raise VMNoSuccessors
        elif len(curr_bb.succ) == 1:
            #  case 2: end of the block and one target
            log.debug("Next stmt is {}".format(curr_bb.succ[0].first_ins.id))
            return curr_bb.succ[0].first_ins.id
        else:
            #  case 3: end of the block and more than one target
            fallthrough_bb = curr_bb.fallthrough_edge

            log.debug("Next stmt is {}".format(fallthrough_bb.first_ins.id))
            return fallthrough_bb.first_ins.id

    def get_non_fallthrough_pc(self, destination_val):
        curr_bb = self.project.factory.block(self.curr_stmt.block_id)

        if not is_concrete(destination_val):
            raise VMSymbolicError('Symbolic jump destination currently not supported.')
        else:
            destination_val = hex(bv_unsigned_value(destination_val))

        candidate_bbs = [bb for bb in curr_bb.succ if bb.id == destination_val or bb.id.startswith(destination_val+"0x")]

        if len(candidate_bbs) == 0:
            raise VMSymbolicError('Unable to find jump destination.')
        elif len(candidate_bbs) > 1:
            raise VMSymbolicError('Multiple jump destinations.')

        non_fallthrough_bb = candidate_bbs[0]

        log.debug("Next stmt is {}".format(non_fallthrough_bb.first_ins.id))
        return non_fallthrough_bb.first_ins.id
    
    def add_constraint(self, constraint):
        # Here you can inspect the constraints being added to the state.
        if opt.STATE_STOP_AT_ADDCONSTRAINT in self.options:
            import ipdb; ipdb.set_trace()
        self.solver.add_path_constraints(constraint)

    # Add here any default plugin that we want to ship
    # with a fresh state.
    def _register_default_plugins(self):
        self.register_plugin("solver", SimStateSolver())
        self.register_plugin("globals", SimStateGlobals())
        if opt.STATE_INSPECT:
            self.register_plugin("inspect", SimStateInspect())

    def register_plugin(self, name: str, plugin: SimStatePlugin):
        self.active_plugins[name] = plugin
        setattr(self, name, plugin)
        plugin.set_state(self)
        return plugin

    def copy(self):
        # assume unchanged xid
        new_state = SymbolicEVMState(self.xid, project=self.project, partial_init=True)

        new_state._pc = self._pc
        new_state.trace = list(self.trace)

        new_state.memory = self.memory.copy(new_state=new_state)
        new_state.storage = self.storage.copy(new_state=new_state)
        new_state.registers = dict(self.registers)
        new_state.ctx = dict(self.ctx)
        new_state.options = list(self.options)
        new_state.callstack = list(self.callstack)
        new_state.returndata = dict(self.returndata)
        new_state.instruction_count = self.instruction_count
        new_state.halt = self.halt
        new_state.revert = self.revert
        new_state.error = self.error
        new_state.gas = self.gas
        new_state.start_balance = self.start_balance
        new_state.balance = self.balance

        new_state.sha_observed = [sha.copy(new_state=new_state) for sha in self.sha_observed]
        new_state.min_timestamp = self.min_timestamp
        new_state.max_timestamp = self.max_timestamp
        new_state.MAX_CALLDATA_SIZE = self.MAX_CALLDATA_SIZE
        new_state.calldata = self.calldata.copy(new_state=new_state)
        new_state.calldatasize = self.calldatasize

        new_state.active_plugins = dict()
        # Copy all the plugins
        for p_name, p in self.active_plugins.items():
            new_state.register_plugin(p_name, p.copy())

        return new_state

    def reset(self, xid):
        self.xid = xid
        self.uuid = SymbolicEVMState.uuid_generator.next()

        # Register default plugins
        self.active_plugins = dict()
        self._register_default_plugins()

        self._pc = None
        self.trace = list()
        self.memory = LambdaMemory(tag=f"MEMORY_{self.xid}", value_sort=BVSort(8), default=BVV(0, 8), state=self)
        self.registers = dict()
        self.ctx = dict()  # todo: is it okay to reset this between transactions??

        self.callstack = list()
        self.returndata = {'size': None, 'instruction_count': None}
        self.instruction_count = 0
        self.halt = False
        self.revert = False
        self.error = None
        self.gas = BVS(f'GAS_{self.xid}', 256)
        self.start_balance = BVS(f'BALANCE_{self.xid}', 256)
        self.balance = BV_Add(self.start_balance, ctx_or_symbolic('CALLVALUE', self.ctx, self.xid))
        self.ctx['CODESIZE-ADDRESS'] = BVV(len(self.code), 256)
        self.sha_observed = list()

        self.calldata = None
        self.calldatasize = None

        return self

    def __str__(self):
        return f"State {self.uuid} at {self.pc}"

    def __repr__(self):
        return str(self)
