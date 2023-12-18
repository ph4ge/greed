# 🕹️ Options

greed supports many option to tweak the behavior of symbolic execution.
These global options should be activated or de-activated before creating an entry state.

| Option Name  | Default | Description |
|----------------------------------------|---------|---------------------------------------------------------------------------------------------------------------------|
| `WEB3_PROVIDER` | http://0.0.0.0:8545  | Web3 provider URI. Used when initializing the partial concrete storage.                                              |
| `LAZY_SOLVES` | False | Indicates whether to check for satisfiability at every fork, affecting exploration speed and state pruning. |
| `GREEDY_SHA` | False | Specifies whether to calculate SHA3 for concrete or single-solution buffers, potentially impacting exploration speed.|
| `SIMGRVIZ` | False | Activates the creation of a graph visualizing the exploration (the SimgrViz Exploration Technique must be also installed|
| `STATE_INSPECT` | False | Activates debugging capabilities through the SimStateInspect plugin (i.e., breakpoints).                             |
| `MAX_CALLDATA_SIZE` | 256 | Default CALLDATASIZE considered, can be overwritten by the entry_state constructor. |
| `MATH_CONCRETIZE_SYMBOLIC_EXP_EXP` | False | Specifies whether to concretize the exponent of an EXP instruction. |
| `MATH_CONCRETIZE_SYMBOLIC_EXP_BASE` | False   | Specifies whether to concretize the base of an EXP instruction. |
| `MATH_MULTIPLY_EXP_THRESHOLD` | 10 | Maximum supported nested multiplications when there is a symbolic base and concrete exponent. |
| `OPTIMISTIC_CALL_RESULTS` | False | Indicates whether to always consider CALLS as succeeded or not.                                                         |
| `DEFAULT_EXTCODESIZE` | False | Specifies whether to use a default constant value for EXTCODESIZE.                                                       |
| `DEFAULT_CREATE_RESULT_ADDRESS` | False  | Specifies whether to use a default constant address when using the CREATE opcode. |
| `DEFAULT_CREATE2_RESULT_ADDRESS` | False  | Specifies whether to use a default constant address when using the CREATE2 opcode. |
| `STATE_STOP_AT_ADDCONSTRAINT` | False | Indicates whether to drop a debugging interface every time a constraint is added to the state.|
| `MAX_SHA_SIZE` | 512 | Maximum size of the SHA3 input buffer considered.|
| `SOLVER` | "YICES2" | Default solver (Yices2).|
| `SOLVER_TIMEOUT` | Inf.   | Timeout setting for the solver. |