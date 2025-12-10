from setuptools import find_packages, setup

setup(
    name="sql_benchmarks",
    packages=find_packages(exclude=["sql_benchmarks_tests"]),
    install_requires=[
        "dagster",
        "dagster-webserver",
        "dagster-postgres",
        "dagster-duckdb",
        "pandas",
        "polars",
        "pyarrow",  # Critical for the new loader
        "psycopg2-binary",
        "sqlalchemy",
        "psutil",
        "pyyaml",
        "numpy"
    ],
    extras_require={"dev": ["pytest"]},
)