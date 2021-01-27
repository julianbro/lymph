import numpy as np
import scipy as sp 
import scipy.stats
from typing import List

class Node(object):
    """Class for lymph node levels (LNLs) in a lymphatic system.

    Args:
        name: Name of the node

        state: Current state this LNL is in. Can be in {0, 1}

        typ: Can be either `"lnl"`, `"tumour"` or `None`. If it is the latter, 
            the type will be inferred from the name of the node. A node 
            starting with a `t` (case-insensitive), then it will be a tumour 
            node and a lymph node levle (lnl) otherwise. (default: `None`)

        obs_table: An arrray of 2x2 matrices. Each of those matrices represents 
            an observational modality. The (0,0) entry corresponds to the 
            specificity :math:`s_P` and at (1,1) one finds the sensitivity 
            :math:`s_N`. These matrices must be column-stochastic.
    """
    def __init__(self, 
                 name: str, 
                 state: int = 0, 
                 typ: str = None, 
                 obs_table: np.ndarray = np.array([[[1, 0], 
                                                    [0, 1]]])):
        
        self.name = name
        if typ is None:
            if self.name.lower()[0] == 't':
                self.typ = "tumour"
            else:
                self.typ = "lnl"
        else:
            self.typ = typ

        # Tumours are always involved, so their state is always 1
        if self.typ == "tumour":
            self.state = 1
        else:
            self.state = state

        self.n_obs = obs_table.shape[0]
        self.obs_table = obs_table

        self.inc = []
        self.out = []



    def report(self):
        """Just quickly print infos about the node.
        """
        print(f"name: {self.name} ({self.typ}), state: {self.state}")
        print("incoming: ", end="")
        
        for i in self.inc:
            print(f"{i.start.name}, ", end="")
        print("\noutgoing: ", end="")
        
        for o in self.out:
            print(f"{o.end.name}, ", end="")
        print("\n", end="")



    def trans_prob(self, log: bool = False) -> float:
        """Computes the transition probabilities from the current state to all
        other possible states.
        
        Args:
            log: If ``True`` method returns the log-probability. 
                (default: ``False``)
        
        Returns:
            The transition probabilities from current state to all two other 
                states.
        """
        res = np.array([1., 0.])

        if self.state == 1:
            if log:
                return np.array([-np.inf, 0.])
            else:
                return np.array([0., 1.])

        for edge in self.inc:
            res[1] += res[0] * edge.t * edge.start.state

            res[0] *= (1 - edge.t) ** edge.start.state
            
        if log:
            return np.log(res)
        else:
            return res



    def obs_prob(self, 
                 log: bool = False, 
                 observation: List[int] = None) -> float:
        """Compute the probability of observing a certain modality, given its 
        current state.

        Args:
            log: If ``True``, method returns the log-prob.

            observation: Contains an observation for each modality. 
                ``shape=(n_obs,)`` (default: ``False``)

        Returns:
            The observation probability.
        """
        res = 1
        if observation is not None:
            for i in range(self.n_obs):
                res *= self.obs_table[i, observation[i], self.state]

        if log:
            return np.log(res)
        else:
            return res



    def bn_prob(self, log: bool = False) -> float:
        """Computes the conditional probability of a node being in the state it 
        is in, given its parents are in the states they are in.

        Args:
            log: If ``True``, returns the log-probability.
                (default: ``False``)

        Returns:
            The conditional (log-)probability.
        """
        res = 1.
        for edge in self.inc:
            res *= (1 - edge.t)**edge.start.state

        res *= (-1)**self.state
        res += self.state

        if log:
            return np.log(res)
        else:
            return res