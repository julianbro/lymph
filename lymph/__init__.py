"""
This package contains code to model the spread of microscopic metastases
through a system of lymph node levels (LNLs), using either a Bayesian network
or a hidden Markov model.
"""

from lymph._version import version

__version__ = version
__description__ = "Package for statistical modelling of lymphatic metastatic spread."
__author__ = "Roman Ludwig"
__email__ = "roman.ludwig@usz.ch"
__uri__ = "https://github.com/rmnldwg/lymph"

# nopycln: file

from lymph.bilateral import Bilateral, BilateralSystem
from lymph.edge import Edge
from lymph.midline import MidlineBilateral
from lymph.node import LymphNodeLevel, Tumor
from lymph.descriptors.diagnose_times import Distribution, DistributionDict
from lymph.unilateral import Unilateral
from lymph.helper import clinical, pathological

__all__ = [
    "LymphNodeLevel",
    "Tumor",
    "Edge",
    "Unilateral",
    "Bilateral", "BilateralSystem",
    "MidlineBilateral",
    "Distribution", "DistributionDict",
    "clinical", "pathological",
]
