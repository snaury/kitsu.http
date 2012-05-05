import os
from setuptools import setup

def read(name):
    return open(os.path.join(os.path.dirname(__file__), name), 'r').read()

setup(
    name="kitsu.http",
    version="0.0.7",
    description="Low-level HTTP library for Python",
    long_description=read('README'),
    author="Alexey Borzenkov",
    author_email="snaury@gmail.com",
    url="https://github.com/snaury/kitsu.http",
    license="MIT License",
    platforms=['any'],
    namespace_packages=['kitsu', 'kitsu.http'],
    packages=['kitsu', 'kitsu.http'],
    test_suite='tests.test_suite',
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
