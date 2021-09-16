from setuptools import setup, find_packages
import logging
logger = logging.getLogger(__name__)

name = 'jupyter_grade_server'
package_name = name
version = '0.1.0'
base_url = 'https://github.com/cduck'

try:
    with open('README.md', 'r') as f:
        long_desc = f.read()
except:
    logger.warning('Could not open README.md.  long_description will be set to None.')
    long_desc = None

setup(
    name = package_name,
    packages = find_packages(),
    version = version,
    description = 'XQueue Pull Grader for Jupyter notebooks',
    long_description = long_desc,
    long_description_content_type = 'text/markdown',
    url = f'{base_url}/{name}',
    download_url = f'{base_url}/{name}/archive/{version}.tar.gz',
    keywords = ['quantum computing', 'feynman path', 'path sum', 'jupyter'],
    classifiers = [
        'License :: OSI Approved :: MIT License',
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Framework :: IPython',
        'Framework :: Jupyter',
    ],
    install_requires=open('requirements/production.txt', 'rb').readlines()
)
