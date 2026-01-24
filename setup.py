from setuptools import setup, find_packages

setup(
    name='giveaway_engine',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'django>=3.2',
        'djangorestframework',
        'requests',
    ],
    classifiers=[
        'Framework :: Django',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
    ],
)
