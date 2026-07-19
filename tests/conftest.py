# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Shared pytest fixtures for wake tests."""
from __future__ import annotations

import pytest


PARALLEL_NETCDF_WORK = {
    "openalex_id": "W2156077349",
    "title": "Parallel netCDF: A High-Performance Scientific I/O Interface",
    "authors": ["Jianwei Li", "Wei-keng Liao", "Alok Choudhary"],
    "year": 2003,
    "venue": "Proceedings of the 2003 ACM/IEEE Conference on Supercomputing",
    "venue_type": "conference",
    "doi": "10.1145/1048935.1050189",
    "url": "https://doi.org/10.1145/1048935.1050189",
    "cited_by_count": 408,
    "type": "proceedings-article",
    "abstract": (
        "This paper presents Parallel netCDF, a high-performance parallel I/O library "
        "for accessing netCDF files in a parallel computing environment. "
        "The library provides a portable and efficient I/O interface for scientific applications."
    ),
    "topics": ["High-performance computing", "Scientific computing"],
}


SAMPLE_CITING_WORKS = [
    {
        "openalex_id": "W1000000001",
        "title": "HDF5: A New Parallel I/O System Built on Parallel netCDF",
        "authors": ["Alice Smith", "Bob Jones"],
        "year": 2005,
        "venue": "SC05: Proceedings of the 2005 ACM/IEEE Conference on Supercomputing",
        "venue_type": "conference",
        "doi": "10.1145/fake.001",
        "cited_by_count": 250,
        "type": "proceedings-article",
        "abstract": "We build a new parallel I/O system using Parallel netCDF as the foundation.",
        "topics": ["High-performance computing"],
    },
    {
        "openalex_id": "W1000000002",
        "title": "Climate Model Output Analysis Using PnetCDF",
        "authors": ["Carol Davis"],
        "year": 2008,
        "venue": "Journal of Computational Science",
        "venue_type": "journal",
        "doi": "10.1016/fake.002",
        "cited_by_count": 42,
        "type": "journal-article",
        "abstract": "We use PnetCDF to efficiently read and write climate model output.",
        "topics": ["Climate science"],
    },
    {
        "openalex_id": "W1000000003",
        "title": "A Survey of Parallel I/O Libraries",
        "authors": ["Dave Wilson"],
        "year": 2010,
        "venue": "ACM Computing Surveys",
        "venue_type": "journal",
        "doi": None,
        "cited_by_count": 5,
        "type": "journal-article",
        "abstract": None,
        "topics": ["Software engineering"],
    },
]
