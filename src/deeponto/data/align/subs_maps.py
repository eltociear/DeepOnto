# Copyright 2021 Yuan He (KRR-Oxford). All rights reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Generate Subsumption Mappings from Equivalence Mappings"""

import random
from collections import defaultdict
from typing import Tuple

from deeponto.onto.text.text_utils import unfold_iri, abbr_iri
from deeponto.onto.graph.graph_utils import (
    super_thing_classes_of,
    sub_thing_classes_of,
    thing_class_descendants_of,
    thing_class_ancestors_of,
)
from deeponto.onto import Ontology
from deeponto.utils import uniqify
from deeponto.onto.mapping import OntoMappings

subs_rels = ["<", ">"]  # "<" means broadMatch (IS-A); ">" means narrowMatch (more specific)


class SubsumptionMappingGenerator:
    def __init__(
        self,
        src_onto: Ontology,
        tgt_onto: Ontology,
        rel: str,
        equiv_mappings_path: str,
        max_subs_ratio: int = 1,  # maximum subsumption mappings generated form an equiv mapping
        # delete_equiv_src: bool = False,
        is_delete_equiv_tgt: bool = True,
        max_hop: int = 3,  # maximum hops between a subsumption class pair
    ):
        # super().__init__(src_onto, tgt_onto)
        self.src_onto = src_onto
        self.tgt_onto = tgt_onto
        self.rel = rel
        # the move function is either towards ancestors or descendants
        if self.rel == "<":
            self.move = lambda x: super_thing_classes_of(x)
        elif self.rel == ">":
            self.move = lambda x: sub_thing_classes_of(x)
        else:
            raise ValueError(f"Unknown subsumption relation: {self.rel}")
        self.max_hop = max_hop

        self.equiv_maps = OntoMappings.read_tsv_mappings(equiv_mappings_path)
        self.equiv_pairs = self.equiv_maps.to_tuples()
        # easy check for equivalence mappings
        check_pair = random.choice(self.equiv_pairs)
        assert check_pair[0] in self.src_onto.class2idx.keys()
        assert check_pair[1] in self.tgt_onto.class2idx.keys()

        self.sub_pairs = []
        self.hop_record = dict()  # record at how many hops is each subs pair constructed
        self.max_subs_ratio = max_subs_ratio

        #  self.delete_equiv_src = delete_equiv_src  # delete the source equiv class or not
        self.is_delete_equiv_tgt = is_delete_equiv_tgt  # delete the target equiv class or not
        self.delete_status = defaultdict(
            lambda: False
        )  # keep track which entites are marked for deletion
        self.construct_status = defaultdict(
            lambda: False
        )  # keep track which entites are marked for construction

    def renew_subs(self):
        self.sub_pairs = []
        self.hop_record = dict()
        self.delete_status = defaultdict(
            lambda: False
        )  # keep track which entites are marked for deletion
        self.construct_status = defaultdict(
            lambda: False
        )  # keep track which entites are marked for construction
        print("Initialize new subsumption generation record ...")

    def static_subs_construct(self):
        """A *static* algorithm for subsumption mapping construction:
        1. mark all equiv targets as to be deleted;
        2. skip all these equiv targets in subs construction.
        This algorithm is *static* because the class marking is performed
        before subsumption mapping construction.
        """
        self.renew_subs()
        # (1) mark all equiv targets as to be deleted
        if self.is_delete_equiv_tgt:
            for _, tgt_equiv in self.equiv_pairs:
                tgt_equiv_ent = self.tgt_onto.owl.search(iri=unfold_iri(tgt_equiv))[0]
                # mark deleted only if any subs can be generated
                if self.move(tgt_equiv_ent):
                    self.delete_status[tgt_equiv] = True

        for src_equiv, tgt_equiv in self.equiv_pairs:
            self.sub_pairs += self.subs_from_an_equiv(src_equiv, tgt_equiv)
        # remove duplicates
        self.sub_pairs = uniqify(self.sub_pairs)

    def online_subs_construct(self):
        """An *online* algorithm for subsumption mapping construction:
        1. an equiv pair is skipped if the target side is marked constructed;
        2. a subs pair is skipped if the target side is marked deleted.
        This algorithm is *online* because the class marking is performed for
        each equiv pair instantly.
        """
        self.renew_subs()
        for src_equiv, tgt_equiv in self.equiv_pairs:
            # (1) an equiv pair is skipped if the target side is marked constructed
            if self.is_delete_equiv_tgt and self.construct_status[tgt_equiv]:
                continue
            # get subs pairs from current equiv pair
            cur_subs = self.subs_from_an_equiv(src_equiv, tgt_equiv)
            # if any subs are generated, mark the target class for deletion
            if self.is_delete_equiv_tgt and cur_subs:
                self.delete_status[tgt_equiv] = True
            # feed to the final output
            self.sub_pairs += cur_subs
        # remove duplicates
        self.sub_pairs = uniqify(self.sub_pairs)

    def subs_from_an_equiv(self, src_ent_name: str, tgt_ent_name: str):
        """Generate subsumption candidates (thus mappings) from the target ontology 
        based on an equivalence mappings; this method adopts BFS to search valid
        ancestors or descendants (of the target equiv class) that are not marked as
        to be deleted. The deletion-marked list is updated outside this method.
        """
        tgt_ent = self.tgt_onto.owl.search(iri=unfold_iri(tgt_ent_name))[0]
        # NOTE: do not construct what have been deleted
        valid_neighbours = []
        frontier = [tgt_ent]
        explored = []
        hop = 1
        num_added = 0
        while len(valid_neighbours) < self.max_subs_ratio and hop <= self.max_hop:
            cur_hop_neighbours = []
            for ent in frontier:
                neighbours_of_ent = self.move(ent)
                for neighbour in neighbours_of_ent:
                    neighbour_name = abbr_iri(neighbour.iri)
                    # deleted targets were updated outside of this method
                    # (2) a subs pair is skipped if the target side is marked deleted
                    if self.is_delete_equiv_tgt and self.delete_status[neighbour_name]:
                        continue
                    self.hop_record[src_ent_name, neighbour_name] = hop
                    valid_neighbours.append(neighbour_name)
                    print(f"found ({tgt_ent_name} {self.rel}) {neighbour_name} at {hop} hops ...")
                    # update the construction status for the neighbour (target side)
                    self.construct_status[neighbour_name] = True
                    num_added += 1
                    if num_added == self.max_subs_ratio:
                        break
                cur_hop_neighbours += neighbours_of_ent
                explored.append(ent)
            # renew the frontier to the next hops neighbours along the correct direction
            frontier = list(set(cur_hop_neighbours) - set(explored))
            hop += 1

        # combine target neighbours with source entity to form subsumption mappings
        subs_pairs = [(src_ent_name, neighbour_name) for neighbour_name in valid_neighbours]
        # assert len(subs_pairs) == len(set(subs_pairs))

        # NOTE: this is an ad-hoc online deletion process
        # if self.is_delete_equiv_tgt:
        #     self.deleted_tgts.append(tgt_ent_name)

        return uniqify(subs_pairs)

    def preserved_tgt_iris(self):
        """Return target class IRIs that are not marked for deletion
        """
        preserved = []
        for tgt_ent_name in self.tgt_onto.class2idx.keys():
            if not self.delete_status[tgt_ent_name]:
                preserved.append(unfold_iri(tgt_ent_name))
        return preserved

    def validate_subs(self, subs_pair: Tuple[str]):
        """Validate if a subsumption mapping based on the equivalent mappings
        """
        src_ent_name, tgt_ent_name = subs_pair
        tgt_ent = self.tgt_onto.owl.search(iri=unfold_iri(tgt_ent_name))[0]
        if self.rel == "<":
            subs_related = lambda e: thing_class_ancestors_of(e)
        elif self.rel == ">":
            subs_related = lambda e: thing_class_descendants_of(e)

        for equiv_tgt_name in self.equiv_maps.ranked[src_ent_name].keys():
            equiv_tgt = self.tgt_onto.owl.search(iri=unfold_iri(equiv_tgt_name))[0]
            if tgt_ent in subs_related(equiv_tgt):
                return True

        return False
