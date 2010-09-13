import os
from setuptools import setup

def read(name):
    return open(os.path.join(os.path.dirname(__file__), name), 'r').read()

setup(
    name="kitsu.http",
    version="0.0.1",
    description="Low-level HTTP library",
    long_description=read('README'),
    author="Alexey Borzenkov",
    author_email="snaury@gmail.com",
    url="http://git.kitsu.ru/mine/kitsu-http.git",
    license="MIT License",
    platforms=['any'],
    packages=['kitsu', 'kitsu.http'],
    zip_safe=True,
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
