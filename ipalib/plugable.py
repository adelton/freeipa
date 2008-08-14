# Authors:
#   Jason Gerard DeRose <jderose@redhat.com>
#
# Copyright (C) 2008  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; version 2 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

"""
Generic plugin framework.

The classes in this module make heavy use of Python container emulation. If
you are unfamiliar with this Python feature, see
http://docs.python.org/ref/sequence-types.html
"""

import re
import inspect
import errors


class ReadOnly(object):
    """
    Base class for classes with read-only attributes.

    Be forewarned that Python does not offer true read-only user defined
    classes. In particular, do not rely upon the read-only-ness of this
    class for security purposes.

    The point of this class is not to make it impossible to set or delete
    attributes, but to make it impossible to accidentally do so. The plugins
    are not thread-safe: in the server, they are loaded once and the same
    instances will be used to process many requests. Therefore, it is
    imperative that they not set any instance attributes after they have
    been initialized. This base class enforces that policy.

    For example:

    >>> class givenname(ReadOnly):
    >>>     def __init__(self):
    >>>         self.whatever = 'some value' # Hasn't been locked yet
    >>>         self.__lock__()
    >>>
    >>>     def finalize(self, api):
    >>>         # After the instance has been locked, attributes can still be
    >>>         # set, but only in a round-about, unconventional way:
    >>>         object.__setattr__(self, 'api', api)
    >>>
    >>>     def normalize(self, value):
    >>>         # After the instance has been locked, trying to set an
    >>>         # attribute in the normal way will raise AttributeError.
    >>>         self.value = value # Not thread safe!
    >>>         return self.actually_normalize()
    >>>
    >>>     def actually_normalize(self):
    >>>         # Again, this is not thread safe:
    >>>         return unicode(self.value).strip()
    """
    __locked = False

    def __lock__(self):
        """
        Puts this instance into a read-only state, after which attempting to
        set or delete an attribute will raise AttributeError.
        """
        assert self.__locked is False, '__lock__() can only be called once'
        self.__locked = True

    def __islocked__(self):
        """
        Returns True if this instance is locked, False otherwise.
        """
        return self.__locked

    def __setattr__(self, name, value):
        """
        Raises an AttributeError if `ReadOnly.__lock__()` has already been
        called; otherwise calls object.__setattr__().
        """
        if self.__locked:
            raise AttributeError('read-only: cannot set %s.%s' %
                (self.__class__.__name__, name)
            )
        return object.__setattr__(self, name, value)

    def __delattr__(self, name):
        """
        Raises an AttributeError if `ReadOnly.__lock__()` has already been
        called; otherwise calls object.__delattr__().
        """
        if self.__locked:
            raise AttributeError('read-only: cannot del %s.%s' %
                (self.__class__.__name__, name)
            )
        return object.__delattr__(self, name)


def lock(obj):
    """
    Convenience function to lock a `ReadOnly` instance.
    """
    assert isinstance(obj, ReadOnly)
    obj.__lock__()
    assert obj.__islocked__()
    return obj


class Plugin(ReadOnly):
    """
    Base class for all plugins.
    """
    __public__ = frozenset()
    __api = None

    def __get_name(self):
        """
        Convenience property to return the class name.
        """
        return self.__class__.__name__
    name = property(__get_name)

    def __get_doc(self):
        """
        Convenience property to return the class docstring.
        """
        return self.__class__.__doc__
    doc = property(__get_doc)

    def __get_api(self):
        """
        Returns the `API` instance passed to `finalize()`, or
        or returns None if `finalize()` has not yet been called.
        """
        return self.__api
    api = property(__get_api)

    @classmethod
    def implements(cls, arg):
        """
        Returns True if this cls.__public__ frozenset contains `arg`;
        returns False otherwise.

        There are three different ways this can be called:

        With a <type 'str'> argument, e.g.:

        >>> class base(ProxyTarget):
        >>>     __public__ = frozenset(['some_attr', 'another_attr'])
        >>> base.implements('some_attr')
        True
        >>> base.implements('an_unknown_attribute')
        False

        With a <type 'frozenset'> argument, e.g.:

        >>> base.implements(frozenset(['some_attr']))
        True
        >>> base.implements(frozenset(['some_attr', 'an_unknown_attribute']))
        False

        With any object that has a `__public__` attribute that is
        <type 'frozenset'>, e.g.:

        >>> class whatever(object):
        >>>     __public__ = frozenset(['another_attr'])
        >>> base.implements(whatever)
        True

        Unlike ProxyTarget.implemented_by(), this returns an abstract answer
        because only the __public__ frozenset is checked... a ProxyTarget
        need not itself have attributes for all names in __public__
        (subclasses might provide them).
        """
        assert type(cls.__public__) is frozenset
        if isinstance(arg, str):
            return arg in cls.__public__
        if type(getattr(arg, '__public__', None)) is frozenset:
            return cls.__public__.issuperset(arg.__public__)
        if type(arg) is frozenset:
            return cls.__public__.issuperset(arg)
        raise TypeError(
            "must be str, frozenset, or have frozenset '__public__' attribute"
        )

    @classmethod
    def implemented_by(cls, arg):
        """
        Returns True if:

            1. ``arg`` is an instance of or subclass of this class, and

            2. ``arg`` (or ``arg.__class__`` if instance) has an attribute for
                each name in this class's ``__public__`` frozenset

        Otherwise, returns False.

        Unlike `Plugin.implements`, this returns a concrete answer because
        the attributes of the subclass are checked.

        :param arg: An instance of or subclass of this class.
        """
        if inspect.isclass(arg):
            subclass = arg
        else:
            subclass = arg.__class__
        assert issubclass(subclass, cls), 'must be subclass of %r' % cls
        for name in cls.__public__:
            if not hasattr(subclass, name):
                return False
        return True

    def finalize(self, api):
        """
        After all the plugins are instantiated, `API` calls this method,
        passing itself as the only argument. This is where plugins should
        check that other plugins they depend upon have actually been loaded.

        :param api: An `API` instance.
        """
        assert self.__api is None, 'finalize() can only be called once'
        assert api is not None, 'finalize() argument cannot be None'
        self.__api = api

    def __repr__(self):
        """
        Returns a fully qualified module_name.class_name() representation that
        could be used to construct this Plugin instance.
        """
        return '%s.%s()' % (
            self.__class__.__module__,
            self.__class__.__name__
        )


class Proxy(ReadOnly):
    """
    Allows access to only certain attributes on a `Plugin`.

    Think of a proxy as an agreement that "I will have at most these
    attributes". This is different from (although similar to) an interface,
    which can be thought of as an agreement that "I will have at least these
    attributes".
    """
    __slots__ = (
        '__base',
        '__target',
        '__name_attr',
        '__public__',
        'name',
        'doc',
    )

    def __init__(self, base, target, name_attr='name'):
        """
        :param base: A subclass of `Plugin`.
        :param target: An instance ``base`` or a subclass of ``base``.
        :param name_attr: The name of the attribute on ``target`` from which
            to derive ``self.name``.
        """
        if not inspect.isclass(base):
            raise TypeError(
                '`base` must be a class, got %r' % base
            )
        if not isinstance(target, base):
            raise ValueError(
                '`target` must be an instance of `base`, got %r' % target
            )
        self.__base = base
        self.__target = target
        self.__name_attr = name_attr
        self.__public__ = base.__public__
        self.name = getattr(target, name_attr)
        self.doc = target.doc
        self.__lock__()
        assert type(self.__public__) is frozenset

    def implements(self, arg):
        """
        Returns True if this proxy implements `arg`. Calls the corresponding
        classmethod on ProxyTarget.

        Unlike ProxyTarget.implements(), this is not a classmethod as a Proxy
        only implements anything as an instance.
        """
        return self.__base.implements(arg)

    def __clone__(self, name_attr):
        """
        Returns a Proxy instance identical to this one except the proxy name
        might be derived from a different attribute on the target. The same
        base and target will be used.
        """
        return self.__class__(self.__base, self.__target, name_attr)

    def __iter__(self):
        """
        Iterates (in ascending order) though the attribute names this proxy is
        allowing access to.
        """
        for name in sorted(self.__public__):
            yield name

    def __getitem__(self, key):
        """
        If this proxy allows access to an attribute named `key`, return that
        attribute.
        """
        if key in self.__public__:
            return getattr(self.__target, key)
        raise KeyError('no proxy attribute %r' % key)

    def __getattr__(self, name):
        """
        If this proxy allows access to an attribute named `name`, return that
        attribute.
        """
        if name in self.__public__:
            return getattr(self.__target, name)
        raise AttributeError('no proxy attribute %r' % name)

    def __call__(self, *args, **kw):
        """
        Attempts to call target.__call__(); raises KeyError if `__call__` is
        not an attribute this proxy allows access to.
        """
        return self['__call__'](*args, **kw)

    def __repr__(self):
        """
        Returns a Python expression that could be used to construct this Proxy
        instance given the appropriate environment.
        """
        return '%s(%s, %r, %r)' % (
            self.__class__.__name__,
            self.__base.__name__,
            self.__target,
            self.__name_attr,
        )


def check_name(name):
    """
    Raises `errors.NameSpaceError` if ``name`` is not a valid Python identifier
    suitable for use in a `NameSpace`.

    :param name: Identifier to test.
    """
    assert type(name) is str, 'must be %r' % str
    regex = r'^[a-z][_a-z0-9]*[a-z0-9]$'
    if re.match(regex, name) is None:
        raise errors.NameSpaceError(name, regex)
    return name


class NameSpace(ReadOnly):
    """
    A read-only namespace with handy container behaviours.

    Each member of a NameSpace instance must have a ``name`` attribute whose
    value:

        1. Is unique among the members
        2. Passes the `check_name()` function

    Beyond that, no restrictions are placed on the members: they can be
    classes or instances, and of any type.

    The members can be accessed as attributes on the NameSpace instance or
    through a dictionary interface. For example, assuming ``obj`` is a member
    in the NameSpace instance ``namespace``, you could do this:

    >>> obj is getattr(namespace, obj.name) # As attribute
    True
    >>> obj is namespace[obj.name] # As dictionary item
    True

    Here is a more detailed example:

    >>> class member(object):
    ...     def __init__(self, i):
    ...             self.name = 'member_%d' % i
    ...
    >>> def get_members(cnt):
    ...     for i in xrange(cnt):
    ...             yield member(i)
    ...
    >>> namespace = NameSpace(get_members(2))
    >>> namespace.member_0 is namespace['member_0']
    True
    >>> len(namespace) # Returns the number of members in namespace
    2
    >>> list(namespace) # As iterable, iterates through the member names
    ['member_0', 'member_1']
    >>> list(namespace()) # Calling a NameSpace iterates through the members
    [<__main__.member object at 0x836710>, <__main__.member object at 0x836750>]
    >>> 'member_1' in namespace # NameSpace.__contains__()
    True
    """

    def __init__(self, members):
        """
        :param members: An iterable providing the members.
        """
        self.__d = dict()
        self.__names = tuple(self.__member_iter(members))
        self.__lock__()
        assert set(self.__d) == set(self.__names)

    def __member_iter(self, members):
        """
        Helper method called only from `NameSpace.__init__()`.

        :param members: Same iterable passed to `NameSpace.__init__()`.
        """
        for member in members:
            name = check_name(member.name)
            assert not (
                name in self.__d or hasattr(self, name)
            ), 'already has member named %r' % name
            self.__d[name] = member
            setattr(self, name, member)
            yield name

    def __len__(self):
        """
        Returns the number of members in this NameSpace.
        """
        return len(self.__d)

    def __contains__(self, name):
        """
        Returns True if instance contains a member named ``name``, otherwise
        False.

        :param name: The name of a potential member
        """
        return name in self.__d

    def __getitem__(self, name):
        """
        Returns the member named ``name``.

        Raises KeyError if this NameSpace does not contain a member named
        ``name``.

        :param name: The name of member to retrieve
        """
        if name in self.__d:
            return self.__d[name]
        raise KeyError('NameSpace has no member named %r' % name)

    def __iter__(self):
        """
        Iterates through the member names in the same order as the members
        were passed to the constructor.
        """
        for name in self.__names:
            yield name

    def __call__(self):
        """
        Iterates through the members in the same order they were passed to the
        constructor.
        """
        for name in self.__names:
            yield self.__d[name]

    def __repr__(self):
        """
        Returns pseudo-valid Python expression that could be used to construct
        this NameSpace instance.
        """
        return '%s(<%d members>)' % (self.__class__.__name__, len(self))


class DictProxy(ReadOnly):
    """
    A read-only dict whose items can also be accessed as attributes.

    Although a DictProxy is read-only, the underlying dict can change (and is
    assumed to).

    One of these is created for each allowed base in a `Registrar` instance.
    """
    def __init__(self, d):
        """
        :param d: The ``dict`` instance to proxy.
        """
        assert type(d) is dict, '`d` must be %r, got %r' % (dict, type(d))
        self.__d = d
        lock(self)

    def __len__(self):
        """
        Returns number of items in underlying ``dict``.
        """
        return len(self.__d)

    def __iter__(self):
        """
        Iterates through keys of underlying ``dict`` in ascending order.
        """
        for name in sorted(self.__d):
            yield name

    def __contains__(self, key):
        """
        Returns True if underlying dict contains ``key``, False otherwise.

        :param key: The key to query upon.
        """
        return key in self.__d

    def __getitem__(self, key):
        """
        Returns value from underlying dict corresponding to ``key``.

        :param key: The key of the value to retrieve.
        """
        if key in self.__d:
            return self.__d[key]
        raise KeyError('no item at key %r' % key)

    def __getattr__(self, name):
        """
        Returns value from underlying dict corresponding to ``name``.

        :param name: The name of the attribute to retrieve.
        """
        if name in self.__d:
            return self.__d[name]
        raise AttributeError('no attribute %r' % name)


class Registrar(ReadOnly):
    """
    Collects plugin classes as they are registered.

    The Registrar does not instantiate plugins... it only implements the
    override logic and stores the plugins in a namespace per allowed base
    class.

    The plugins are instantiated when `API.finalize()` is called.
    """
    def __init__(self, *allowed):
        """
        :param allowed: Base classes from which plugins accepted by this
            Registrar must subclass.
        """

        class Val(ReadOnly):
            """
            Internal class used so that only one mapping is needed.
            """
            def __init__(self, base):
                assert inspect.isclass(base)
                self.base = base
                self.name = base.__name__
                self.sub_d = dict()
                self.dictproxy = DictProxy(self.sub_d)
                lock(self)

        self.__allowed = allowed
        self.__d = {}
        self.__registered = set()
        for base in self.__allowed:
            val = Val(base)
            assert not (
                val.name in self.__d or hasattr(self, val.name)
            )
            self.__d[val.name] = val
            setattr(self, val.name, val.dictproxy)
        lock(self)

    def __findbases(self, klass):
        """
        Iterates through allowed bases that ``klass`` is a subclass of.

        Raises `errors.SubclassError` if ``klass`` is not a subclass of any
        allowed base.

        :param klass: The class to find bases for.
        """
        assert inspect.isclass(klass)
        found = False
        for base in self.__allowed:
            if issubclass(klass, base):
                found = True
                yield base
        if not found:
            raise errors.SubclassError(klass, self.__allowed)

    def __call__(self, klass, override=False):
        """
        Register the plugin ``klass``.

        :param klass: A subclass of `Plugin` to attempt to register.
        :param override: If true, override an already registered plugin.
        """
        if not inspect.isclass(klass):
            raise TypeError('plugin must be a class: %r'  % klass)

        # Raise DuplicateError if this exact class was already registered:
        if klass in self.__registered:
            raise errors.DuplicateError(klass)

        # Find the base class or raise SubclassError:
        for base in self.__findbases(klass):
            sub_d = self.__d[base.__name__].sub_d

            # Check override:
            if klass.__name__ in sub_d:
                # Must use override=True to override:
                if not override:
                    raise errors.OverrideError(base, klass)
            else:
                # There was nothing already registered to override:
                if override:
                    raise errors.MissingOverrideError(base, klass)

            # The plugin is okay, add to sub_d:
            sub_d[klass.__name__] = klass

        # The plugin is okay, add to __registered:
        self.__registered.add(klass)

    def __getitem__(self, key):
        """
        Returns the DictProxy for plugins subclassed from the base named ``key``.
        """
        if key not in self.__d:
            raise KeyError('no base class named %r' % key)
        return self.__d[key].dictproxy

    def __contains__(self, key):
        """
        Returns True if a base class named ``key`` is in this Registrar.
        """
        return key in self.__d

    def __iter__(self):
        """
        Iterates through a (base, registered_plugins) tuple for each allowed
        base.
        """
        for base in self.__allowed:
            sub_d = self.__d[base.__name__].sub_d
            yield (base, tuple(sub_d[k] for k in sorted(sub_d)))


class API(ReadOnly):
    __finalized = False

    def __init__(self, *allowed):
        self.__keys = tuple(b.__name__ for b in allowed)
        self.register = Registrar(*allowed)
        self.__lock__()

    def finalize(self):
        """
        Finalize the registration, instantiate the plugins.
        """
        assert not self.__finalized, 'finalize() can only be called once'
        d = {}
        def plugin_iter(base, classes):
            for cls in classes:
                if cls not in d:
                    d[cls] = cls()
                plugin = d[cls]
                yield Proxy(base, plugin)

        for (base, classes) in self.register:
            ns = NameSpace(plugin_iter(base, classes))
            assert not hasattr(self, base.__name__)
            object.__setattr__(self, base.__name__, ns)
        for plugin in d.values():
            plugin.finalize(self)
            plugin.__lock__()
            assert plugin.__islocked__() is True
            assert plugin.api is self
        object.__setattr__(self, '_API__finalized', True)

    def __iter__(self):
        for key in self.__keys:
            yield key
