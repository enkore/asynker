from setuptools import setup, find_packages

description = open('README.rst', 'r', encoding='utf-8').read()

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

    url='https://github.com/enkore/asynker',
    author='Marian Beermann',
    author_email='asynker@enkore.de',

    license='MIT',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
    ],

    packages=find_packages('src'),
    package_dir={'': 'src'},
)
