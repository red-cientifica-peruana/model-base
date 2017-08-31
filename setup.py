import os.path
from setuptools import setup, find_packages

package_dir = os.path.abspath(os.path.dirname(__file__))
version_file = os.path.join(package_dir, "version")
with open(version_file) as version_file_handle:
    version = version_file_handle.read()

setup(
    name = "model-base",
    version = version,
    description = "Viracocha Model Base",
    package_dir = {"":"src"},
    packages = find_packages("src"),
    install_requires=[
        "sqlalchemy==1.1.10"
    ],
    dependency_links=[
        "git+https://github.com/red-cientifica-peruana/falcon-exceptions.git#egg=falcon_exceptions"
    ],
    author = 'DevTeam RCP',
    author_email = 'devteam@rcp.pe',
    url = 'https://git.rcp.pe/devteam/model-base',
    keywords = ['viracocha', 'model', 'base']
)
