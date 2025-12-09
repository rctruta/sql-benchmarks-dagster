from setuptools import find_packages, setup

setup(
    name="sql_benchmarks",
    packages=find_packages(exclude=["sql_benchmarks_tests"]),
    install_requires=[
        "dagster",
        "dagster-cloud",
        "psutil"
    ],
    extras_require={"dev": ["dagster-webserver", "pytest", "sqlparse"]},
)
