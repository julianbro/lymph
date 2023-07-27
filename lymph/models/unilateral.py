"""
The main module of this package.

It implements the lymphatic system as a graph of `Tumor` and `LymphNodeLevel` nodes,
connected by instances of `Edge`.

The resulting class can compute all kinds of conditional probabilities with respect to
the (microscopic) involvement of lymph node levels (LNLs) due to the spread of a tumor.
"""
from __future__ import annotations

import base64
import warnings
from typing import Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd
from numpy.linalg import matrix_power as mat_pow

from lymph.descriptors import diagnose_times, matrix, modalities, params
from lymph.graph import Edge, LymphNodeLevel, Tumor
from lymph.helper import change_base, check_unique_names


class Unilateral:
    """
    Class that models metastatic progression in a lymphatic system.

    It does this by representing it as a directed graph. The progression itself can be
    modelled via hidden Markov models (HMM) or Bayesian networks (BN).
    """

    edge_params = params.Lookup()
    """Dictionary that maps parameter names to their corresponding `Param` objects.

    Parameter names are constructed from the names of the tumors and LNLs in the graph
    that represents the lymphatic system. For example, the parameter for the spread
    probability from the tumor `T` to the LNL `I` is accessed via the key
    `spread_T_to_I`.

    The parameters can be read out and changed via the `get` and `set` methods of the
    `Param` objects. The `set` method also deletes the transition matrix, so that it
    needs to be recomputed when accessing it the next time.
    """

    diag_time_dists = diagnose_times.DistributionLookup()
    """Mapping of T-categories to the corresponding distributions over diagnose times.

    Every distribution is represented by a `diagnose_times.Distribution` object, which
    holds the parametrized and frozen versions of the probability mass function over
    the diagnose times. They are used to marginalize over the (generally unknown)
    diagnose times when computing e.g. the likelihood.
    """

    def __init__(
        self,
        graph: Dict[Tuple[str], Set[str]],
        tumor_state: Optional[int] = None,
        allowed_states: Optional[List[int]] = None,
        **_kwargs,
    ) -> None:
        """Create a new instance of the `Unilateral` class.

        The graph that represents the lymphatic system is given as a dictionary. Its
        keys are tuples of the form `("tumor", "<tumor_name>")` or
        `("lnl", "<lnl_name>")`. The values are sets of strings that represent the
        names of the nodes that are connected to the node given by the key.
        """
        if allowed_states is None:
            allowed_states = [0, 1]

        if tumor_state is None:
            tumor_state = allowed_states[-1]

        check_unique_names(graph)
        self.init_nodes(graph, tumor_state, allowed_states)
        self.init_edges(graph)


    @classmethod
    def binary(cls, graph: Dict[Tuple[str], Set[str]], **kwargs) -> Unilateral:
        """Create a new instance of the `Unilateral` class with binary LNLs."""
        return cls(graph, allowed_states=[0, 1], **kwargs)


    @classmethod
    def trinary(cls, graph: Dict[Tuple[str], Set[str]], **kwargs) -> Unilateral:
        return cls(graph, allowed_states=[0, 1, 2], **kwargs)


    def __str__(self) -> str:
        """Print info about the instance."""
        return f"Unilateral with {len(self.tumors)} tumors and {len(self.lnls)} LNLs"


    def init_nodes(self, graph, tumor_state, allowed_lnl_states):
        """Initialize the nodes of the graph."""
        self.tumors: List[Tumor] = []
        self.lnls: List[LymphNodeLevel] = []

        for node_type, node_name in graph:
            if node_type == "tumor":
                self.tumors.append(
                    Tumor(name=node_name, state=tumor_state)
                )
            elif node_type == "lnl":
                self.lnls.append(
                    LymphNodeLevel(name=node_name, allowed_states=allowed_lnl_states)
                )


    def init_edges(self, graph):
        """Initialize the edges of the graph.

        When a `LymphNodeLevel` is trinary, it is connected to itself via a growth edge.
        """
        self.tumor_edges: List[Edge] = []
        self.lnl_edges: List[Edge] = []
        self.growth_edges: List[Edge] = []

        for (_, start_name), end_names in graph.items():
            start = self.find_node(start_name)
            if isinstance(start, LymphNodeLevel) and start.is_trinary:
                growth_edge = Edge(parent=start, child=start)
                self.growth_edges.append(growth_edge)

            for end_name in end_names:
                end = self.find_node(end_name)
                new_edge = Edge(parent=start, child=end)

                if new_edge.is_tumor_spread:
                    self.tumor_edges.append(new_edge)
                else:
                    self.lnl_edges.append(new_edge)


    @property
    def allowed_states(self) -> List[int]:
        """Return the list of allowed states for the LNLs."""
        return self.lnls[0].allowed_states


    @property
    def is_binary(self) -> bool:
        """Returns True if the graph is binary, False otherwise."""
        res = {node.is_binary for node in self.lnls}

        if len(res) != 1:
            raise RuntimeError("Not all lnls have the same number of states")

        return res.pop()


    @property
    def is_trinary(self) -> bool:
        """Returns True if the graph is trinary, False otherwise."""
        res = {node.is_trinary for node in self.lnls}

        if len(res) != 1:
            raise RuntimeError("Not all lnls have the same number of states")

        return res.pop()


    @property
    def nodes(self) -> List[Union[Tumor, LymphNodeLevel]]:
        """List of all nodes in the graph."""
        return self.tumors + self.lnls


    @property
    def edges(self) -> List[Edge]:
        """List of all edges in the graph."""
        return self.tumor_edges + self.lnl_edges + self.growth_edges


    def find_node(self, name: str) -> Union[Tumor, LymphNodeLevel, None]:
        """Finds and returns a node with name `name`."""
        for node in self.nodes:
            if node.name == name:
                return node
        return None


    @property
    def graph(self) -> Dict[Tuple[str, str], Set[str]]:
        """Returns the graph representing this instance's nodes and egdes."""
        res = {}
        for node in self.nodes:
            node_type = "tumor" if isinstance(node, Tumor) else "lnl"
            res[(node_type, node.name)] = {o.child.name for o in node.out}
        return res


    def print_graph(self):
        """generates the a a visual chart of the spread model based on mermaid graph

        Returns:
            list: list with the string to create the mermaid graph and an url that directly leads to the graph
        """
        graph = ('flowchart TD\n')
        for index, node in enumerate(self.nodes):
            for edge in self.nodes[index].out:
                line = f"{node.name} -->|{edge.spread_prob}| {edge.child.name} \n"
                graph += line
        graphbytes = graph.encode("ascii")
        base64_bytes = base64.b64encode(graphbytes)
        base64_string = base64_bytes.decode("ascii")
        url="https://mermaid.ink/img/" + base64_string
        return graph, url


    def print_info(self):
        """Print detailed information about the instance."""
        num_tumors = len(self.tumors)
        num_lnls   = len(self.lnls)
        string = (
            f"Unilateral lymphatic system with {num_tumors} tumor(s) "
            f"and {num_lnls} LNL(s).\n"
            + " ".join([f"{e} {e.spread_prob}%" for e in self.tumor_edges]) + "\n" + " ".join([f"{e} {e.spread_prob}%" for e in self.lnl_edges])
            + f"\n the growth probability is: {self.growth_edges[0].spread_prob}" + f" the micro mod is {self.lnl_edges[0].micro_mod}"
        )
        print(string)


    def get_states(self, as_dict: bool = False) -> Union[Dict[str, int], List[int]]:
        """Return the states of the system's LNLs.

        If `as_dict` is `True`, the result is a dictionary with the names of the LNLs
        as keys and their states as values. Otherwise, the result is a list of the
        states of the LNLs in the order they appear in the graph.
        """
        result = {}

        for lnl in self.lnls:
            result[lnl.name] = lnl.state

        return result if as_dict else list(result.values())


    def assign_states(self, *new_states_args, **new_states_kwargs) -> None:
        """Assign a new state to the system's LNLs.

        The state can either be provided with positional arguments or as keyword
        arguments. In case of positional arguments, the order must be the same as the
        order of the LNLs in the graph. If keyword arguments are used, the keys must be
        the names of the LNLs. The order of the keyword arguments does not matter.

        The keyword arguments override the positional arguments.
        """
        for new_lnl_state, lnl in zip(new_states_args, self.lnls):
            lnl.state = new_lnl_state

        for key, value in new_states_kwargs.items():
            lnl = self.find_node(key)
            if lnl is not None and isinstance(lnl, LymphNodeLevel):
                lnl.state = value


    def get_params(self, as_dict: bool = False) -> Union[Dict[str, float], List[float]]:
        """Return a dictionary of all parameters and their currently set values.

        If `as_dict` is `True`, the result is a dictionary with the names of the
        edge parameters as keys and their values as values. Otherwise, the result is a
        list of the values of the edge parameters in the order they appear in the
        graph.
        """
        result = {}
        for name, param in self.edge_params.items():
            result[name] = param.get()

        for name, dist in self.diag_time_dists.items():
            result[name] = dist.get_param()

        return result if as_dict else list(result.values())


    def assign_params(self, *new_params_args, **new_params_kwargs):
        """Assign new parameters to the model.

        The parameters can either be provided with positional arguments or as
        keyword arguments. The positional arguments must be in the following order:

        1. All spread probs from tumor to the LNLs
        2. The spread probs from LNL to LNL. If the model is trinary, the microscopic
            parameter is set right after the corresponding LNL's spread prob.
        3. The growth parameters for each trinary LNL. For a binary model,
            this is skipped.
        4. The parameters for the marginalizing distributions over diagnose times

        The order of the keyword arguments obviously does not matter. Also, if one
        wants to set the microscopic or growth parameters globally for all LNLs, the
        keyword arguments ``micro_mod`` and ``growth`` should be used.

        The keyword arguments override the positional arguments.
        """
        params_access = [
            *[param.set for param in self.edge_params.values()],
            *[getattr(dist, "update") for dist in self.diag_time_dists.values()]
        ]
        for setter, new_param_value in zip(params_access, new_params_args):
            setter(new_param_value)

        for key, value in new_params_kwargs.items():
            if key in self.diag_time_dists:
                self.diag_time_dists[key].update(value)

            elif key == "growth":
                for edge in self.growth_edges:
                    edge.spread_prob = value

            elif key == "micro_mod":
                for edge in self.lnl_edges:
                    edge.micro_mod = value

            else:
                self.edge_params[key].set(value)


    modalities = modalities.Lookup()
    """Dictionary storing diagnostic modalities and their specificity/sensitivity.

    The keys are the names of the modalities, e.g. "CT" or "pathology", the values are
    instances of the `Modality` class. When setting the modality, the value can be
    a `Modality` object, a confusion matrix (`np.ndarray`) or a list/tuple with
    specificity and sensitivity.

    One can then access the confusion matrix of a modality.
    """


    def comp_transition_prob(
        self,
        newstate: List[int],
        assign: bool = False
    ) -> float:
        """Computes the probability to transition to ``newstate``, given its
        current state.

        Args:
            newstate: List of new states for each LNL in the lymphatic
                system. The transition probability :math:`t` will be computed
                from the current states to these states.
            assign: if ``True``, after computing and returning the probability,
                the system updates its own state to be ``newstate``.
                (default: ``False``)

        Returns:
            Transition probability :math:`t`.
        """
        trans_prob = 1
        for i, lnl in enumerate(self.lnls):
            trans_prob *= lnl.comp_trans_prob(new_state = newstate[i])
            if trans_prob == 0:
                break

        if assign:
            self.assign_states(newstate)

        return trans_prob


    def comp_diagnose_prob(
        self,
        diagnoses: Union[pd.Series, Dict[str, Dict[str, bool]]]
    ) -> float:
        """Compute the probability to observe a diagnose given the current
        state of the network.

        Args:
            diagnoses: Either a pandas ``Series`` object corresponding to one
                row of a patient data table, or a dictionary with keys of
                diagnostic modalities and values of dictionaries holding the
                observation for each LNL under the respective key.

        Returns:
            The probability of observing this particular combination of
            diagnoses, given the current state of the system.
        """
        prob = 1.
        for name, modality in self.modalities.items():
            if name in diagnoses:
                mod_diagnose = diagnoses[name]
                for lnl in self.lnls:
                    try:
                        lnl_diagnose = mod_diagnose[lnl.name]
                    except KeyError:
                        continue
                    except IndexError as idx_err:
                        raise ValueError(
                            "diagnoses were not provided in the correct format"
                        ) from idx_err
                    prob *= lnl.comp_obs_prob(lnl_diagnose, modality.confusion_matrix)
        return prob


    def _gen_state_list(self):
        """Generates the list of (hidden) states.
        """
        if not hasattr(self, "_state_list"):
            self._state_list = np.zeros(
                shape=(len(self.allowed_states)**len(self.lnls), len(self.lnls)), dtype=int
            )
        for i in range(len(self.allowed_states)**len(self.lnls)):
            self._state_list[i] = [
                int(digit) for digit in change_base(i, len(self.allowed_states), length=len(self.lnls))
            ]

    @property
    def state_list(self):
        """Return list of all possible hidden states. They are arranged in the
        same order as the lymph node levels in the network/graph.
        """
        try:
            return self._state_list
        except AttributeError:
            self._gen_state_list()
            return self._state_list


    def _gen_obs_list(self):
        """Generates the list of possible observations.
        """
        n_obs = len(self.modalities)

        if not hasattr(self, "_obs_list"):
            self._obs_list = np.zeros(
                shape=(2**(n_obs * len(self.lnls)), n_obs * len(self.lnls)),
                dtype=int
            )

        for i in range(2**(n_obs * len(self.lnls))):
            tmp = change_base(i, 2, reverse=False, length=n_obs * len(self.lnls))
            for j in range(len(self.lnls)):
                for k in range(n_obs):
                    self._obs_list[i,(j*n_obs)+k] = int(tmp[k*len(self.lnls)+j])

    @property
    def obs_list(self):
        """Return the list of all possible observations.
        """
        try:
            return self._obs_list
        except AttributeError:
            self._gen_obs_list()
            return self._obs_list


    transition_matrix = matrix.Transition()
    """The matrix encoding the probabilities to transition from one state to another.

    This is the crucial object for modelling the evolution of the probabilistic
    system in the context of the hidden Markov model.

    It is recomputed every time the parameters along the edges of the graph are
    changed.
    """

    observation_matrix = matrix.Observation()
    """The matrix encoding the probabilities to observe a certain diagnosis."""


    def _gen_diagnose_matrices(self, table: pd.DataFrame, t_stage: str):
        """Generate the matrix containing the probabilities to see the provided
        diagnose, given any possible hidden state. The resulting matrix has
        size :math:`2^N \\times M` where :math:`N` is the number of nodes in
        the graph and :math:`M` the number of patients.

        Args:
            table: pandas ``DataFrame`` containing rows of patients. Must have
                ``MultiIndex`` columns with two levels: First, the modalities
                and second, the LNLs.
            t_stage: The T-stage all the patients in ``table`` belong to.
        """
        if not hasattr(self, "_diagnose_matrices"):
            self._diagnose_matrices = {}

        shape = (len(self.state_list), len(table))
        self._diagnose_matrices[t_stage] = np.ones(shape=shape)

        for i,state in enumerate(self.state_list):
            self.assign_states(state)

            for j, (_, patient) in enumerate(table.iterrows()):
                patient_obs_prob = self.comp_diagnose_prob(patient)
                self._diagnose_matrices[t_stage][i,j] = patient_obs_prob


    @property
    def diagnose_matrices(self):
        try:
            return self._diagnose_matrices
        except AttributeError as att_err:
            raise AttributeError(
                "No data has been loaded and hence no observation matrix has "
                "been computed."
            ) from att_err


    @property
    def patient_data(self):
        """Table with rows of patients. Must have a two-level
        :class:`MultiIndex` where the top-level has categories 'info' and the
        name of the available diagnostic modalities. Under 'info', the second
        level is only 't_stage', while under the modality, the names of the
        diagnosed lymph node levels are given as the columns. Such a table
        could look like this:

        +---------+----------------------+-----------------------+
        |  info   |         MRI          |          PET          |
        +---------+----------+-----------+-----------+-----------+
        | t_stage |    II    |    III    |    II     |    III    |
        +=========+==========+===========+===========+===========+
        | early   | ``True`` | ``False`` | ``True``  | ``False`` |
        +---------+----------+-----------+-----------+-----------+
        | late    | ``None`` | ``None``  | ``False`` | ``False`` |
        +---------+----------+-----------+-----------+-----------+
        | early   | ``True`` | ``True``  | ``True``  | ``None``  |
        +---------+----------+-----------+-----------+-----------+
        """
        try:
            return self._patient_data
        except AttributeError as att_err:
            raise AttributeError("No patient data has been loaded yet") from att_err

    @patient_data.setter
    def patient_data(self, patient_data: pd.DataFrame):
        """Load the patient data. For now, this just calls the :meth:`load_data`
        method, but at a later point, I would like to write a function here
        that generates the pandas :class:`DataFrame` from the internal matrix
        representation of the data.
        """
        self._patient_data = patient_data.copy()
        self.load_data(patient_data)


    def load_data(
        self,
        data: pd.DataFrame,
        modality_spsn: Optional[Dict[str, List[float]]] = None,
        mode: str = "HMM",
    ):
        """
        Transform tabular patient data (:class:`pd.DataFrame`) into internal
        representation, consisting of one or several matrices
        :math:`\\mathbf{C}_{T}` that can marginalize over possible diagnoses.

        Args:
            data: Table with rows of patients. Must have a two-level
                :class:`MultiIndex` where the top-level has categories 'info'
                and the name of the available diagnostic modalities. Under
                'info', the second level is only 't_stage', while under the
                modality, the names of the diagnosed lymph node levels are
                given as the columns. Such a table could look like this:

                +---------+----------------------+-----------------------+
                |  info   |         MRI          |          PET          |
                +---------+----------+-----------+-----------+-----------+
                | t_stage |    II    |    III    |    II     |    III    |
                +=========+==========+===========+===========+===========+
                | early   | ``True`` | ``False`` | ``True``  | ``False`` |
                +---------+----------+-----------+-----------+-----------+
                | late    | ``None`` | ``None``  | ``False`` | ``False`` |
                +---------+----------+-----------+-----------+-----------+
                | early   | ``True`` | ``True``  | ``True``  | ``None``  |
                +---------+----------+-----------+-----------+-----------+

            modality_spsn: Dictionary of specificity :math:`s_P` and :math:`s_N`
                (in that order) for each observational/diagnostic modality. Can
                be ommitted if the modalities where already defined.

            mode: `"HMM"` for hidden Markov model and `"BN"` for Bayesian net.
        """
        if modality_spsn is not None:
            self.modalities = modality_spsn
        elif self.modalities == {}:
            raise ValueError("No diagnostic modalities have been defined yet!")

        # when first loading data with with different T-stages, and then loading a
        # dataset with fewer T-stages, the old diagnose matrices should not be preserved
        if hasattr(self, "_diagnose_matrices"):
            del self._diagnose_matrices

        # For the Hidden Markov Model
        if mode=="HMM":
            t_stages = list(set(data[("info", "t_stage")]))

            for stage in t_stages:
                table = data.loc[
                    data[('info', 't_stage')] == stage,
                    self.modalities.keys()
                ]
                self._gen_diagnose_matrices(table, stage)
                if stage not in self.diag_time_dists:
                    warnings.warn(
                        "No distribution for marginalizing over diagnose times has "
                        f"been defined for T-stage {stage}. During inference, all "
                        "patients in this T-stage will be ignored."
                    )

        # For the Bayesian Network
        elif mode=="BN":
            table = data[self.modalities.keys()]
            stage = "BN"
            self._gen_diagnose_matrices(table, stage)


    def _evolve(
        self, t_first: int = 0, t_last: Optional[int] = None
    ) -> np.ndarray:
        """Evolve hidden Markov model based system over time steps. Compute
        :math:`p(S \\mid t)` where :math:`S` is a distinct state and :math:`t`
        is the time.

        Args:
            t_first: First time-step that should be in the list of returned
                involvement probabilities.

            t_last: Last time step to consider. This function computes
                involvement probabilities for all :math:`t` in between
                ``t_frist`` and ``t_last``. If ``t_first == t_last``,
                :math:`p(S \\mid t)` is computed only at that time.

        Returns:
            A matrix with the values :math:`p(S \\mid t)` for each time-step.

        :meta public:
        """
        # All healthy state at beginning
        start_state = np.zeros(shape=len(self.state_list), dtype=float)
        start_state[0] = 1.

        # compute involvement at first time-step
        state = start_state @ mat_pow(self.transition_matrix, t_first)

        if t_last is None:
            return state

        len_time_range = t_last - t_first
        if len_time_range < 0:
            msg = ("Starting time must be smaller than ending time.")
            raise ValueError(msg)

        state_probs = np.zeros(
            shape=(len_time_range + 1, len(self.state_list)),
            dtype=float
        )

        # compute subsequent time-steps, effectively incrementing time until end
        for i in range(len_time_range):
            state_probs[i] = state
            state = state @ self.transition_matrix

        state_probs[-1] = state

        return state_probs


    def _likelihood(
        self,
        mode: str = "HMM",
        log: bool = True,
    ) -> float:
        """
        Compute the (log-)likelihood of stored data, using the stored spread probs
        and parameters for the marginalizations over diagnose times (if the respective
        distributions are parametrized).

        This is the core method for computing the likelihood. The user-facing API calls
        it after doing some preliminary checks with the passed arguments.
        """
        # hidden Markov model
        if mode == "HMM":
            stored_t_stages = set(self.diagnose_matrices.keys())
            provided_t_stages = set(self.diag_time_dists.keys())
            t_stages = list(stored_t_stages.intersection(provided_t_stages))

            max_t = self.diag_time_dists.max_t
            evolved_model = self._evolve(t_last=max_t)

            llh = 0. if log else 1.
            for stage in t_stages:
                p = (
                    self.diag_time_dists[stage].pmf
                    @ evolved_model
                    @ self.diagnose_matrices[stage]
                )
                if log:
                    llh += np.sum(np.log(p))
                else:
                    llh *= np.prod(p)

        # likelihood for the Bayesian network
        elif mode == "BN":
            state_probs = np.ones(shape=(len(self.state_list),), dtype=float)

            for i, state in enumerate(self.state_list):
                self.assign_states(state)
                for node in self.lnls:
                    state_probs[i] *= node.bn_prob()

            p = state_probs @ self.diagnose_matrices["BN"]
            llh = np.sum(np.log(p)) if log else np.prod(p)
        return llh


    def likelihood(
        self,
        data: Optional[pd.DataFrame] = None,
        given_params: Optional[dict] = None,
        log: bool = True,
        mode: str = "HMM"
    ) -> float:
        """
        Compute (log-)likelihood of (already stored) data, given the probabilities of
        spread in the network and the parameters for the distributions used to
        marginalize over the diagnose times.

        Args:
            data: Table with rows of patients and columns of per-LNL involvment. See
                :meth:`load_data` for more details on how this should look like.

            given_params: The likelihood is a function of these parameters. They mainly
                consist of the :attr:`spread_probs` of the model. Any excess parameters
                will be used to update the parametrized distributions used for
                marginalizing over the diagnose times (see :attr:`diag_time_dists`).

            log: When ``True``, the log-likelihood is returned.

            mode: Compute the likelihood using the Bayesian network (``"BN"``) or
                the hidden Markv model (``"HMM"``). When using the Bayesian net, no
                marginalization over diagnose times is performed.

        Returns:
            The (log-)likelihood :math:`\\log{p(D \\mid \\theta)}` where :math:`D`
            is the data and :math:`\\theta` are the given parameters.
        """
        if data is not None:
            self.patient_data = data

        if given_params is None:
            return self._likelihood(mode, log)

        try:
            self.assign_params(**given_params)
        except ValueError:
            return -np.inf if log else 0.

        return self._likelihood(mode, log)


    def risk(
        self,
        involvement: Optional[Union[dict, np.ndarray]] = None,
        given_params: Optional[dict] = None,
        given_diagnoses: Optional[Dict[str, dict]] = None,
        t_stage: str = "early",
        mode: str = "HMM",
        **_kwargs,
    ) -> Union[float, np.ndarray]:
        """Compute risk(s) of involvement given a specific (but potentially
        incomplete) diagnosis.

        Args:
            involvement: Specific hidden involvement one is interested in. If only parts
                of the state are of interest, the remainder can be masked with
                values ``None``. If specified, the functions returns a single
                risk.

            given_params: The risk is a function of these parameters. They mainly
                consist of the :attr:`spread_probs` of the model. Any excess parameters
                will be used to update the parametrized distributions used for
                marginalizing over the diagnose times (see :attr:`diag_time_dists`).

            given_diagnoses: Dictionary that can hold a potentially incomplete (mask
                with ``None``) diagnose for every available modality. Leaving
                out available modalities will assume a completely missing
                diagnosis.

            t_stage: The T-stage for which the risk should be computed. The attribute
                :attr:`diag_time_dists` must have a distribution for marginalizing
                over diagnose times stored for this T-stage.

            mode: Set to ``"HMM"`` for the hidden Markov model risk (requires
                the ``time_dist``) or to ``"BN"`` for the Bayesian network
                version.

        Returns:
            A single probability value if ``involvement`` is specified and an array
            with probabilities for all possible hidden states otherwise.
        """
        if given_params is not None:
            self.assign_params(**given_params)

        if given_diagnoses is None:
            given_diagnoses = {}

        # vector containing P(Z=z|X)
        diagnose_probs = np.zeros(shape=len(self.state_list))
        for i,state in enumerate(self.state_list):
            self.assign_states(state)
            diagnose_probs[i] = self.comp_diagnose_prob(given_diagnoses)
        # vector P(X=x) of probabilities of arriving in state x, marginalized over time
        # HMM version
        if mode == "HMM":
            max_t = self.diag_time_dists.max_t
            state_probs = self._evolve(t_last=max_t)
            marg_state_probs = self.diag_time_dists[t_stage].pmf @ state_probs

        # BN version
        elif mode == "BN":
            marg_state_probs = np.ones(shape=(len(self.state_list)), dtype=float)
            for i, state in enumerate(self.state_list):
                self.assign_states(state)
                for node in self.lnls:
                    marg_state_probs[i] *= node.bn_prob()

        # multiply P(Z=z|X) * P(X) elementwise to get vector of joint probs P(Z=z,X)
        joint_diag_state = marg_state_probs * diagnose_probs
        # get marginal over X from joint
        marg_diagnose_prob = np.sum(joint_diag_state)
        # compute vector of probabilities for all possible involvements given
        # the specified diagnosis P(X|Z=z)
        post_state_probs =  joint_diag_state / marg_diagnose_prob
        if involvement is None:
            return post_state_probs

        # if a specific involvement of interest is provided, marginalize the
        # resulting vector of hidden states to match that involvement of
        # interest
        if isinstance(involvement, dict):
            involvement = np.array([involvement.get(lnl.name, None) for lnl in self.lnls])
        else:
            involvement = np.array(involvement)

        marg_states = np.zeros(shape=post_state_probs.shape, dtype=bool)
        for i,state in enumerate(self.state_list):
            marg_states[i] = np.all(np.equal(
                involvement, state,
                where=(involvement!=None),
                out=np.ones_like(state, dtype=bool)
            ))
        return marg_states @ post_state_probs


    def _draw_patient_diagnoses(
        self,
        diag_times: List[int],
    ) -> np.ndarray:
        """Draw random possible observations for a list of T-stages and
        diagnose times.

        Args:
            diag_times: List of diagnose times for each patient who's diagnose
                is supposed to be drawn.
        """
        max_t = np.max(diag_times)

        # use the drawn diagnose times to compute probabilities over states and
        # diagnoses
        per_time_state_probs = self._evolve(t_last=max_t)
        per_patient_state_probs = per_time_state_probs[diag_times]
        per_patient_obs_probs = per_patient_state_probs @ self.observation_matrix

        # then, draw a diagnose from the possible ones
        obs_idx = np.arange(len(self.obs_list))
        drawn_obs_idx = [
            np.random.choice(obs_idx, p=obs_prob)
            for obs_prob in per_patient_obs_probs
        ]
        drawn_obs = self.obs_list[drawn_obs_idx].astype(bool)
        return drawn_obs


    def generate_dataset(
        self,
        num_patients: int,
        stage_dist: Dict[str, float],
        **_kwargs,
    ) -> pd.DataFrame:
        """Generate/sample a pandas :class:`DataFrame` from the defined network
        using the samples and diagnostic modalities that have been set.

        Args:
            num_patients: Number of patients to generate.
            stage_dist: Probability to find a patient in a certain T-stage.
        """
        drawn_t_stages, drawn_diag_times = self.diag_time_dists.draw(
            dist=stage_dist, size=num_patients
        )

        drawn_obs = self._draw_patient_diagnoses(drawn_diag_times)

        # construct MultiIndex for dataset from stored modalities
        modality_names = list(self.modalities.keys())
        lnl_names = [lnl.name for lnl in self.lnls]
        multi_cols = pd.MultiIndex.from_product([modality_names, lnl_names])

        # create DataFrame
        dataset = pd.DataFrame(drawn_obs, columns=multi_cols)
        dataset[('info', 't_stage')] = drawn_t_stages

        return dataset
