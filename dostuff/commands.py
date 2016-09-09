import asyncio
from collections import namedtuple
from functools import lru_cache, reduce
import pathlib
import subprocess
import sys

DRY_RUN = True
Error = namedtuple('Error', 'reason')
Ok = namedtuple('Ok', 'changed')


async def run(*args):
    echo = ['echo'] if DRY_RUN else []
    process = await asyncio.create_subprocess_exec(
        *echo, *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if DRY_RUN:
        sys.stdout.buffer.write(stdout)
    return stdout, stderr


class ValidationError(Exception):
    pass


class Command:
    def __repr__(self):
        varlist = ' '.join(
            '{}={}'.format(name, value)
            for name, value in vars(self).items()
            if not name.startswith('_')
        )
        return '<{}{}>'.format(self.__class__.__name__, ' ' + varlist if varlist else '')

    def validate(self):
        pass


class Nothing(Command):
    async def do(self):
        pass


class Check(Command):
    def __init__(self, exists=None, reason=None):
        super().__init__()
        self.exists = pathlib.Path(exists) if exists is not None else None
        self.reason = reason

    async def do(self):
        if self.exists:
            if self.exists.exists():
                return Ok(changed=False)
            else:
                return Error(reason)

    def validate(self):
        if not self.exists:
            raise ValidationError("--exists was not specified")


class File(Command):
    def __init__(self, destination, source=None):
        super().__init__()
        self.destination = pathlib.Path(destination)
        assert self.destination.is_absolute()
        if source is None:
            self.source = pathlib.Path(self.destination.name)
        else:
            self.source = pathlib.Path(source)

    async def do(self):
        await asyncio.sleep(1)
        await run(
            'cp',
            str(self.source),
            str(self.destination),
        )
        return Ok(changed=True)


class Package(Command):
    _instance = None
    packages = {
        'install': set(),
        'remove': set(),
    }

    def __new__(cls, *packages, action='install'):
        assert action in cls.packages

        if not cls._instance:
            cls._instance = super().__new__(cls)

        cls.packages[action].update(packages)
        return cls._instance

    @lru_cache(maxsize=1)
    async def do(self):
        for flags, packages in [
            ('-Rs', self.packages['remove']),
            ('-S', self.packages['install']),
        ]:
            if packages:
                await run(
                    'pacman',
                    flags,
                    *sorted(packages),
                )
        return Ok(changed=False)

    def validate(self):
        duplicate_packages = self.packages['install'] & self.packages['remove']
        if duplicate_packages:
            raise ValidationError("packages being both installed and removed: %r" % duplicate_packages)


class Service(Command):
    def __init__(self, name, action='enable', config=Nothing(), file=Nothing()):
        super().__init__()
        self.name = name
        self.action = action
        self.config = config
        self.file = file
        assert isinstance(self.config, Command)
        assert isinstance(self.file, Command)

    async def do(self):
        config_result = await self.config.do()
        file_result = await self.file.do()
        await run(
            'systemctl',
            self.action,
            self.name,
        )
        if config_result.changed:
            await run(
                'systemctl',
                'reload',
                self.name,
            )
        return Ok(changed=False)


class User(Command):
    def __init__(self, name, homedir=False, system=False):
        super().__init__()
        self.name = name
        self.homedir = homedir
        self.system = system

    async def do(self):
        args = []
        if self.homedir:
            args.append('--create-home')
        if self.system:
            args.append('--system')
        await run(
            'useradd',
            *args,
            self.name,
        )
        return Ok(changed=False)
