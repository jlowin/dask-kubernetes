import collections
import functools
from math import ceil
import jinja2
import os
import subprocess
import sys
import yaml

import six
import click

defaults = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        'defaults.yaml'))
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        '../kubernetes'))


def required_commands(*commands):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            """
            Fails if any required command is not available
            """
            failed = False
            for command in commands:
                try:
                    # Unix-specific command lookup
                    subprocess.check_output("which {}".format(command), shell=True)
                except subprocess.CalledProcessError:
                    click.echo("Required command does not exist: {}".format(command), err=True)
                    failed = True
            if failed:
                sys.exit(1)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def call(cmd):
    click.secho("executing: {}".format(cmd), fg='green')
    subprocess.call(cmd, shell=True)


def check_output(cmd):
    click.secho("executing: {}".format(cmd), fg='green')
    return subprocess.check_output(cmd, shell=True).decode("utf-8")


def mem_bytes(m):
    """Translate java memory spec to bytes"""
    mult = {'Ki': 2 ** 10, 'Mi': 2 ** 20, 'Gi': 2 ** 30}
    for k, v in mult.items():
        if k in m:
            return v * int(m.replace(k, ''))
    return m


def read_conf(config):
    if isinstance(config, (six.string_types, bytes)):
        if os.path.exists(config):
            with open(config) as f:
                return f.read()
    elif hasattr(config, 'read'):
        return config.read()
    else:
        raise TypeError


def nested_update(d, u):
    """Update dictionary `d` based on `u`, which which may also be
    a dictionary.
    """
    # http://stackoverflow.com/a/3233356/1889400
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            r = nested_update(d.get(k, {}), v)
            d[k] = r
        else:
            d[k] = u[k]
    return d


def parse_cli_override(s):
    r"""foo.bar=baz -> {'foo': {'bar': 'baz'}"""
    key, val = s.split('=')
    keys = key.split('.')

    d = {keys[-1]: val}

    for k in reversed(keys[:-1]):
        d = {k: dict(d)}
    return d


def get_conf(settings, args):
    """Produce configuration dictionary

    Starts with default settings, applies given YAML file, and overrides
    with any further arguments, in that order.

    Parameters
    ----------
    settings: str or None
        YAML file with some or all of the entries in defaults.yaml
    args: list of strings
        Override parameters like "jupyter.port=443"."""
    conf = yaml.load(open(defaults).read())
    if settings is not None:
        settings = yaml.load(read_conf(settings))
        nested_update(conf, settings)

    if args is None:
        overrides = {}
    else:
        overrides = [parse_cli_override(arg) for arg in args]
        for override in overrides:
            nested_update(conf, override)

    # worker memory should be slightly less than container capacity
    factor = float(conf['workers']['mem_factor'])
    conf['workers']['memory_per_worker2'] = int(factor * mem_bytes(
        conf['workers']['memory_per_worker']))
    conf['workers']['cpus_per_worker2'] = ceil(
        conf['workers']['cpus_per_worker'])
    return conf


def render_templates(conf, par):
    """Render given config into kubernetes yaml files, in par directory

    Parameters
    ----------
    conf: dict
        Configuration dictionary, from get_conf()
    par: str
        Directory to write to
    """
    loader = jinja2.PackageLoader("dask_kubernetes", package_path="kubernetes")
    jenv = jinja2.Environment(loader=loader)
    configs = {
        os.path.join(par, name): jenv.get_template(name).render(conf)
        for name in jenv.list_templates()
    }
    return configs


def write_templates(configs):
    for fn, config in configs.items():
        with open(fn, 'wt') as f:
            f.write(config)
