import logging
from typing import List, Mapping

from SEtaac.block import Block
from SEtaac.cfg import CFG
from SEtaac.factory import Factory


class TAC_Function:
    def __init__(self, id: str, name: str, public: bool, blocks: List[Block], arguments: List[str]):
        self.id = id
        self.name = name
        self.public = public
        self.blocks = blocks
        self.arguments = arguments

        self.cfg = None

    # todo: build callgraph
    def get_call_targets(self, factory: Factory) -> List[str]:
        call_targets = []
        for bb in self.blocks:
            for stmt in bb.statements:
                if stmt.__internal_name__ == "CALLPRIVATE":
                    target_bb = stmt.get_target_bb(factory, self.id)
                    call_targets.append(target_bb.id)
        return call_targets

    # Building the intra-functional CFG of a target function.
    def build_cfg(self, factory: Factory, tac_block_succ: Mapping[str, List[str]]):
        cfg = CFG()
        for bb in self.blocks:
            bb.cfg = cfg
            cfg.graph.add_node(bb)

        for a in self.blocks:
            # Adding information about successors from Gigahorse analysis
            for b_id in tac_block_succ.get(a.id, []):
                cfg.graph.add_edge(a, factory.block(b_id))

        cfg.bbs = list(cfg.graph.nodes())
        cfg._bb_at = {bb.id: bb for bb in cfg.bbs}

        cfg.root = factory.block(self.id)

        return cfg
