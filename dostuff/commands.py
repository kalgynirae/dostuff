import asyncio
from collections import namedtuple
from functools import lru_cache, reduce
import pathlib

Result = namedtuple('Result', 'changed')


class Command:
    def __repr__(self):
        vars = [
            '{}={}'.format(name, value)
            for name, value in vars(self).items()
            if not name.startswith('_')
        ]
        return '<{} {}>'.format(self.__class__.__name__, ' '.join(vars))


class Nothing(Command):
    async def do(self):
        pass


class Check(Command):
    def __init__(self, exists=None, reason=None):
        self.exists = exists
        self.reason = reason

    async def do(self):
        return Result(changed=False)


class File(Command):
    def __init__(self, destination, source=None):
        self.destination = pathlib.Path(destination)
        assert self.destination.is_absolute()
        if source is None:
            self.source = pathlib.Path(self.destination.name)
        else:
            self.source = pathlib.Path(source)

    async def do(self):
        await asyncio.sleep(1)
        process = await asyncio.create_subprocess_exec(
            'echo',
            'cp',
            str(self.source),
            str(self.destination),
        )
        await process.wait()
        return Result(changed=True)


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
                process = await asyncio.create_subprocess_exec(
                    'echo',
                    'pacman',
                    flags,
                    *sorted(packages),
                )
                await process.wait()
        return Result(changed=False)

    def validate(self):
        duplicate_packages = packages['install'] & packages['remove']
        if duplicate_packages:
            raise ValueError("packages being both installed and removed: %r" % duplicate_packages)


class Service(Command):
    def __init__(self, name, action='enable', config=Nothing(), file=Nothing()):
        self.name = name
        self.action = action
        self.config = config
        self.file = file
        assert isinstance(self.config, Command)
        assert isinstance(self.file, Command)

    async def do(self):
        config_result = await self.config.do()
        file_result = await self.file.do()
        process = await asyncio.create_subprocess_exec(
            'echo',
            'systemctl',
            self.action,
            self.name,
        )
        await process.wait()
        if config_result.changed:
            print('systemctl reload', self.name)
        return Result(changed=False)


class User(Command):
    def __init__(self, name, homedir=False, system=False):
        self.name = name
        self.homedir = homedir
        self.system = system

    async def do(self):
        args = []
        if self.homedir:
            args.append('--create-home')
        if self.system:
            args.append('--system')
        process = await asyncio.create_subprocess_exec(
            'echo',
            'useradd',
            *args,
            self.name,
        )
        await process.wait()
        return Result(changed=False)
