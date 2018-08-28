from setuptools import setup, find_packages

description = open('README.rst', 'r').read()

setup(
    name='asynker',

    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    tests_require=[
        'asynker[test]',
    ],
    extras_require={
        'test': [
            'pytest',
        ],
    },

    description='Coroutine scheduler for Python 3.5\'s await syntax',
    long_description=description,

    url=None,
    author='Marian Beermann',

    license='MIT',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
    ],

    py_modules='src/asynker.py',
)
