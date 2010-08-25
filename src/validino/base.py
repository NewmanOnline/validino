import datetime
import re
import time
from uuid import UUID, uuid1


__all__ = [
    'Invalid',
    'check',
    'clamp',
    'clamp_length',
    'compose',
    'confirm_type',
    'default',
    'dict_nest',
    'dict_unnest',
    'either',
    'empty',
    'equal',
    'excursion',
    'fields_equal',
    'fields_match',
    'is_list',
    'is_scalar',
    'not_equal',
    'uuid',
    'integer',
    'boolean',
    'to_boolean',
    'not_empty',
    'not_belongs',
    'belongs',
    'parse_date',
    'parse_datetime',
    'parse_time',
    'regex',
    'regex_sub',
    'Schema',
    'strip',
    'to_list',
    'to_scalar',
    'to_unicode',
    'to_string',
    'translate',
    'nested']


def _add_error_message(d, k, msg):
    """
    internal utility for adding an error message to a
    dictionary of messages.
    """
    d.setdefault(k, [])
    if msg not in d[k]:
        d[k].append(msg)

def _msg(msg, key, default):
    """
    internal message-handling routine.
    """
    try:
        return msg.get(key, default)
    except AttributeError:
        if msg is None:
            return default
        else:
            return msg

def dict_nest(data, separator='.'):
    """
    takes a flat dictionary with string keys and turns it into a
    nested one by splitting keys on the given separator.
    """
    res = {}
    for k in data:
        levels = k.split(separator)
        d = res
        for k1 in levels[:-1]:
            d.setdefault(k1, {})
            d = d[k1]
        d[levels[-1]] = data[k]
    return res

def dict_unnest(data, separator='.'):
    """
    takes a dictionary with string keys and values which may be either
    such dictionaries or non-dictionary values, and turns them into a
    flat dictionary with keys consisting of paths into the nested
    structure, with path elements delimited by the given separator.

    This is the inverse operation of dict_nest().
    """
    res = {}
    for k, v in data.iteritems():
        if isinstance(v, dict):
            v = dict_unnest(v, separator)
            for k1, v1 in v.iteritems():
                res["%s%s%s" % (k, separator, k1)] = v1
        else:
            res[k] = v
    return res

class Invalid(Exception):
    # this should support nested exceptions and
    # extracting messages from some context

    def __init__(self,
                 *args,
                 **kw):
        d = {}
        p = []
        for a in args:
            if isinstance(a, dict):
                self._join_dicts(d, a)
            else:
                p.append(a)
        d.update(self._normalize_dict(kw))
        Exception.__init__(self, p)
        self.errors = d
        if p:
            self.message = p[0]
        else:
            self.message = None

    @staticmethod
    def _join_dicts(res, d):
        for k, v in d.iteritems():
            res.setdefault(k, [])
            if not isinstance(v, (list,tuple)):
                res[k].append(v)
            else:
                res[k].extend(v)

    @staticmethod
    def _normalize_dict(d):
        res = {}
        if d:
            for k, v in d.iteritems():
                if not isinstance(v, (list,tuple)):
                    res[k] = [v]
                else:
                    res[k] = v
        return res

    @staticmethod
    def _safe_append(adict, key, thing):
        if not isinstance(thing, (list, dict)):
            thing = [thing]
        try:
            adict[key].extend(thing)
        except KeyError:
            adict[key] = thing

    def add_error_message(self, key, message):
        _add_error_message(self.errors, key, message)

    def unpack_errors(self, force_dict=True, list_of_errors=False):
        if self.errors or force_dict:
            if self.message:
                # drop the top level message if it is empty
                result = {None: [self.message]}
            else:
                result = {}
        else:
            return self.message

        if self.errors:
            for name, msglist in self.errors.iteritems():
                for m in msglist:
                    if isinstance(m, Exception):
                        try:
                            unpacked = m.unpack_errors(force_dict=False)
                        except AttributeError:
                            self._safe_append(result, name, m.args[0])

                        else:
                            if isinstance(unpacked, dict):
                                self._join_dicts(result, unpacked)
                            elif unpacked:
                                self._safe_append(result, name, unpacked)
                    else:
                        self._safe_append(result, name, m)

        if not list_of_errors:
            result = dict([(e, m[0]) for e, m in result.items() if m])

        return result


class Schema(object):
    """
    creates a validator from a dictionary of subvalidators that will
    be used to validate a dictionary of data, returning a new
    dictionary that contains the converted values.

    The keys in the validator dictionary may be either singular -- atoms
    (presumably strings) that match keys in the data dictionary, or
    plural -- lists/tuples of such atoms.

    The values associated with those keys should be subvalidator
    functions (or lists/tuples of functions that will be composed
    automatically) that are passed a value or values taken from the
    data dictionary according to the corresponding key in the data
    dictionary.  If the key is singular, the subvalidator will be
    passed the data dictionary's value for the key (or None); if
    plural, it will be passed a tuple of the data dictionary's values
    for all the items in the plural key (e.g., tuple(data[x] for x in
    key)).  In either case, the return value of the subvalidator
    should match the structure of the input.

    The subvalidators are sorted by key before being executed.  Therefore,
    subvalidators with plural keys will always be executed after those
    with singular keys.

    If allow_missing is False, then any missing keys in the input will
    give rise to an error.  Similarly, if allow_extra is False, any
    extra keys will result in an error.
    """

    def __init__(self,
                 subvalidators,
                 msg=None,
                 allow_missing=True,
                 allow_extra=True,
                 filter_extra=True):
        self.subvalidators = subvalidators
        self.msg = msg
        self.allow_missing = allow_missing
        self.allow_extra = allow_extra
        self.filter_extra = filter_extra

    def _keys(self):
        schemakeys = set()
        for x in self.subvalidators:
            if isinstance(x, (list, tuple)):
                for x1 in x:
                    schemakeys.add(x1)
            else:
                schemakeys.add(x)
        return schemakeys

    def __call__(self, data):
        if not self.filter_extra:
            res = data
        else:
            res = {}
        exceptions = {}
        if not (self.allow_extra and self.allow_missing):
            inputkeys = set(data.keys())
            schemakeys = self._keys()
            if not self.allow_extra:
                if inputkeys.difference(schemakeys):
                    raise Invalid(_msg(self.msg,
                                       'schema.extra',
                                       'extra keys in input'))
            if not self.allow_missing:
                if schemakeys.difference(inputkeys):
                    raise Invalid(_msg(self.msg,
                                       'schema.missing',
                                       'missing keys in input'))

        for k in sorted(self.subvalidators):
            vfunc = self.subvalidators[k]
            if isinstance(vfunc, (list, tuple)):
                vfunc = compose(*vfunc)
            have_plural = isinstance(k, (list,tuple))
            if have_plural:
                vdata = tuple(res.get(x, data.get(x)) for x in k)
            else:
                vdata = res.get(k, data.get(k))
            try:
                tmp = vfunc(vdata)
            except Exception, e:
                # if the exception specifies a field name,
                # let that override the key in the validator
                # dictionary
                name = getattr(e, 'field', k) or k
                exceptions.setdefault(name, [])
                exceptions[name].append(e)
            else:
                if have_plural:
                    res.update(dict(zip(k, tmp)))
                else:
                    res[k] = tmp

        if exceptions:
            raise Invalid(_msg(self.msg,
                               "schema.error",
                               "Problems were found in the submitted data."),
                          exceptions)
        return res


def confirm_type(typespec, msg=None):
    def f(value):
        if isinstance(value, typespec):
            return value
        raise Invalid(_msg(msg,
                           "confirm_type",
                           "unexpected type"))
    return f

def translate(mapping, msg=None):
    def f(value):
        try:
            return mapping[value]
        except KeyError:
            raise Invalid(_msg(msg,
                               "belongs",
                               "invalid choice"))
    return f

def to_unicode(encoding='utf8', errors='strict', msg=None):
    def f(value):
        if isinstance(value, unicode):
            return value
        elif value is None:
            return u''
        else:
            try:
                return value.decode(encoding, errors)
            except AttributeError:
                return unicode(value)
            except UnicodeError, e:
                raise Invalid(_msg(msg,
                                   'to_unicode',
                                   'encoding error'))
    return f

def to_string(encoding='utf8', errors='strict', msg=None):
    def f(value):
        if isinstance(value, str):
            return value
        elif value is None:
            return ''
        else:
            try:
                return value.encode(encoding, errors)
            except AttributeError:
                return str(value)
            except UnicodeError, e:
                raise Invalid(_msg(msg,
                                   'to_string',
                                   'encoding error'))
    return f

def is_scalar(msg=None, listtypes=(list,)):
    """
    Raises an exception if the value is not a scalar.
    """
    def f(value):
        if isinstance(value, listtypes):
            raise Invalid(_msg(msg,
                               'is_scalar',
                               'expected scalar value'))
        return value
    return f

def is_list(msg=None, listtypes=(list,)):
    """
    Raises an exception if the value is not a list.
    """
    def f(value):
        if not isinstance(value, listtypes):
            raise Invalid(_msg(msg,
                               "is_list",
                               "expected list value"))
        return value
    return f

def to_scalar(listtypes=(list,)):
    """
    if the value is a list, return the first element.
    Otherwise, return the value.

    This raises no exceptions.
    """
    def f(value):
        if isinstance(value, listtypes):
            return value[0]
        return value
    return f

def to_list(listtypes=(list,)):
    """
    if the value is a scalar, wrap it in a list.
    Otherwise, return the value.

    This raises no exceptions.
    """
    def f(value):
        if not isinstance(value, listtypes):
            return [value]
        return value
    return f

def default(defaultValue):
    """
    if the value is None, return defaultValue instead.

    This raises no exceptions.
    """
    def f(value):
        if value is None:
            return defaultValue
        return value
    return f

def either(*validators):
    """
    Tries each of a series of validators in turn, swallowing any
    exceptions they raise, and returns the result of the first one
    that works.  If none work, the last exception caught is re-raised.
    """
    last_exception = None
    def f(value):
        for v in validators:
            try:
                value = v(value)
            except Exception, e:
                last_exception = e
            else:
                return value
        raise last_exception
    return f

def compose(*validators):
    """
    Applies each of a series of validators in turn, passing the return
    value of each to the next.
    """
    def f(value):
        for v in validators:
            value = v(value)
        return value
    return f

def check(*validators):
    """
    Returns a function that runs each of a series of validators
    against input data, which is passed to each validator in turn,
    ignoring the validators return value.  The function returns the
    original input data (which, if it mutable, may have been changed).
    """
    def f(value):
        for v in validators:
            v(value)
        return value
    return f

def excursion(*validators):
    """
    perform a series of validations that may break down the data
    passed in into a form that you don't deserve to retain; if the
    data survives validation, you carry on from the point the
    excursion started.
    """
    def f(value):
        compose(*validators)(value)
        return value
    return f

def equal(val, msg=None):
    def f(value):
        if value == val:
            return value
        raise Invalid(_msg(msg, 'eq', 'invalid value'))
    return f

def not_equal(val, msg=None):
    def f(value):
        if value != val:
            return value
        raise Invalid(_msg(msg, 'eq', 'invalid value'))
    return f

def empty(msg=None):
    def f(value):
        if value == '' or value is None:
            return value
        raise Invalid(_msg(msg,
                           "empty",
                           "No value was expected"))
    return f

def not_empty(msg=None):
    def f(value):
        if value != '' and value != None:
            return value
        raise Invalid(_msg(msg,
                           'notempty',
                           "A non-empty value was expected"))
    return f

def strip(value):
    """
    For string/unicode input, strips the value to remove pre- or
    postpended whitespace.  For other values, does nothing; raises no
    exceptions.
    """
    try:
        return value.strip()
    except AttributeError:
        return value

def clamp(min=None, max=None, msg=None):
    """
    clamp a value between minimum and maximum values (either
    of which are optional).
    """
    def f(value):
        if min is not None and value < min:
            raise Invalid(_msg(msg,
                               "min",
                               "value below minimum"))
        if max is not None and value > max:
            raise Invalid(_msg(msg,
                               "max",
                               "value above maximum"))
        return value
    return f

def clamp_length(min=None, max=None, msg=None):
    """
    clamp a value between minimum and maximum lengths (either
    of which are optional).
    """
    def f(value):
        vlen = len(value)
        if min is not None and vlen < min:
            raise Invalid(_msg(msg,
                               "minlen",
                               "too short"))
        if max is not None and vlen > max:
            raise Invalid(_msg(msg,
                               "maxlen",
                               "too long"))
        return value
    return f

def belongs(domain, msg=None):
    """
    ensures that the value belongs to the domain
    specified.
    """
    def f(value):
        if value in domain:
            return value
        raise Invalid(_msg(msg,
                           "belongs",
                           "invalid choice"))
    return f

def not_belongs(domain, msg=None):
    """
    ensures that the value does not belong to the domain
    specified.
    """
    def f(value):
        if value not in domain:
            return value
        raise Invalid(_msg(msg,
                           "not_belongs",
                           "invalid choice"))
    return f

def parse_time(format, msg=None):
    """
    attempts to parse the time according to
    the given format, returning a timetuple,
    or raises an Invalid exception.
    """
    def f(value):
        try:
            return time.strptime(value, format)
        except ValueError:
            raise Invalid(_msg(msg,
                               'parse_time',
                               "invalid time"))
    return f

def parse_date(format, msg=None):
    """
    like parse_time, but returns a datetime.date object.
    """
    def f(value):
        v = parse_time(format, msg)(value)
        return datetime.date(*v[:3])
    return f

def parse_datetime(format, msg=None):
    """
    like parse_time, but returns a datetime.datetime object.
    """
    def f(value):
        v = parse_time(format, msg)(value)
        return datetime.datetime(*v[:6])
    return f

def uuid(msg=None, default=False):
    """
    Accepts any value that can be converted to a uuid
    """
    def f(value):
        try:
            v = str(UUID(str(value)))
        except ValueError:
            if default and not value:
                return uuid1()
            else:
                raise Invalid(_msg(msg,
                                   "uuid",
                                   "invalid uuid"))
        return v
    return f

def integer(msg=None):
    """
    attempts to coerce the value into an integer.
    """
    def f(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise Invalid(_msg(msg,
                               "integer",
                               "not an integer"))
    return f

def boolean(msg=None):
    """
    Ensures the value is one of True or False

    >>> validator = boolean(msg='Is not boolean')
    >>> validator(True)
    True
    >>> validator('true')
    Traceback (most recent call last):
    ...
    Invalid: ['Is not boolean']
    """
    def f(value):
        if value in [True, False]:
            return value
        else:
            raise Invalid(_msg(msg, 'boolean', 'not a boolean'))
    return f

def to_boolean(msg=None):
    """
    Coerces the value to one of True or False

    >>> validator = to_boolean(msg='Me no convert to boolean')
    >>> validator('true')
    True
    >>> validator(0)
    False
    >>> validator([])
    False
    """
    def f(value):
        return bool(value)
    return f

def regex(pat, msg=None):
    """
    tests the value against the given regex pattern
    and raises Invalid if it doesn't match.
    """
    def f(value):
        m = re.match(pat, value)
        if not m:
            raise Invalid(_msg(msg,
                               'regex',
                               "does not match pattern"))
        return value
    return f

def regex_sub(pat, sub):
    """
    performs regex substitution on the input value.
    """
    def f(value):
        return re.sub(pat, sub, value)
    return f

def fields_equal(msg=None, field=None):
    """
    when passed a collection of values,
    verifies that they are all equal.
    """
    def f(values):
        if len(set(values)) != 1:
            m = _msg(msg,
                   'fields_equal',
                   "fields not equal")
            if field is None:
                raise Invalid(m)
            else:
                raise Invalid({field: m})
        return values
    return f

def fields_match(name1, name2, msg=None, field=None):
    """
    verifies that the values associated with the keys 'name1' and
    'name2' in value (which must be a dict) are identical.
    """
    def f(value):
        if value[name1] != value[name2]:
            m = _msg(msg,
                   'fields_match',
                   'fields do not match')
            if field is not None:
                raise Invalid({field: m})
            else:
                raise Invalid(m)
        return value
    return f

def nested(**kwargs):
    """
    Behaves like a dict.  It's keys are names, it's values are validators
    """
    def f(value):
        data = dict()
        for k, v in kwargs.items():
            try:
                data[k] = v(value[k])
            except KeyError:
                raise Invalid
        return data
    return f
