from dagster import Definitions, asset

print("------------------ RELOADING DEFINITIONS ------------------")

@asset
def simple_test_asset():
    return "I exist!"

