from SEtaac.utils import concrete, is_true, get_solver
from SEtaac.exceptions import ExternalData, SymbolicError, IntractablePath, VMException

__all__ = ['TAC_Jump', 'TAC_Jumpi']

class TAC_Jump:
    __internal_name__ = "JUMP"
    def __init__(self, destination):
        self.destination = destination

    def parse(self, raw_stmt):
        pass # todo

    def handle(self, state):
        # todo: implement symbolic jump
        succ = state.copy()
        dest = succ.registers[self.destination]
        if not concrete(dest):
            raise SymbolicError('Symbolic jump target')
        succ.pc = dest

        return [succ]

    def __str__(self):
        return "JUMP {}".format(self.destination)

class TAC_Jumpi:
    __internal_name__ = "JUMPI"
    def __init__(self, condition, destination):
        self.condition = condition
        self.destination = destination

    def parse(self, raw_stmt):
        pass # todo

    def handler(self, state):
        # todo: implement jumpi
        succ = state.copy()
        dest = succ.registers[self.destination]
        cond = succ.registers[self.condition]

        if concrete(cond):
            # if the jump condition is concrete, use it to determine the jump target
            if cond is True:
                if not concrete(dest):
                    raise SymbolicError('Symbolic jump target')
                succ.pc = dest
                return [succ]
            else:
                succ.pc = succ.next_statement()
                return [succ]
        else:
            # todo: fix get_solver
            # let's check if both branches are sat
            s = get_solver()
            s.add(succ.constraints)
            sat_true = is_true(cond == 1, s)
            sat_false = is_true(cond == 0, s)

            if sat_true and sat_false:
                # actually fork here
                succ_true = succ.copy()
                succ_false = succ

                succ_true.pc = dest
                succ_true.constraints.append(cond == 1)

                succ_false.pc = succ.next_statement()
                succ_false.constraints.append(cond == 0)

                return [succ_true, succ_false]
            elif sat_true:
                # if only the true branch is sat, jump
                if not concrete(dest):
                    raise SymbolicError('Symbolic jump target')
                succ.pc = dest
                succ.constraints.append(cond == 1)

                return [succ]
            elif sat_false:
                # if only the false branch is sat, step to the fallthrough branch
                succ.pc = succ.next_statement()
                succ.constraints.append(cond == 0)

                return [succ]
            else:
                # nothing is sat
                return []

    def __str__(self):
        return "JUMPI {} {}".format(self.condition, self.destination)
