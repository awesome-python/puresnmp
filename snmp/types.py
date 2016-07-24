"""
See X690: https://en.wikipedia.org/wiki/X.690
"""

from .exc import SnmpError

def encode_length(value):
    """
    The "length" field must be specially encoded for values above 127.

    See https://en.wikipedia.org/wiki/X.690#Length_octets
    """
    if value & 0b10000000:
        raise NotImplementedError('Length values above 127 are not yet '
                                  'implemented!')
    return value


def consume(data):
    type = data[0]
    length, remainder = consume_length(data[1:])
    chunk = data[:length+2]

    # TODO: The following branches could be automated using the "HEADER"
    # variable from each class.
    if type == 0x02:
        value = Integer.from_bytes(chunk)
    elif type == 0x04:
        value = String.from_bytes(chunk)
    elif type == 0x30:
        value = List.from_bytes(chunk)
    elif type == 0x05:
        value = None
    elif type == 0xa2:
        value = GetResponse.from_bytes(chunk)
    elif type == 0x06:
        value = Oid.from_bytes(chunk)
    else:
        raise ValueError('Unknown type header: 0x%02x' % type)

    return value, remainder[length:]


def consume_length(data):
    if data[0] == 0b11111111:
        # reserved
        raise NotImplementedError('This is a reserved case in X690')
    elif data[0] & 0b10000000 == 0:
        # definite short form
        output = int.from_bytes([data[0]], 'big')
        data = data[1:]
    elif data[0] ^ 0b10000000 == 0:
        # indefinite form
        raise NotImplementedError('Indefinite lenghts are not yet implemented!')
    else:
        # definite long form
        num_octets = int.from_bytes([data[0] ^ 0b10000000], 'big')
        value_octets = data[1:1+num_octets]
        output = int.from_bytes(value_octets, 'big')
        data = data[num_octets + 1:]
    return output, data


class Type:

    @staticmethod
    def from_bytes(data):
        raise NotImplementedError('Not yet implemented')

    def __bytes__(self):
        raise NotImplementedError('Not yet implemented')


class Null(Type):
    HEADER = 0x05

    @staticmethod
    def from_bytes(data):
        if data[0] != Null.HEADER:
            raise ValueError('Invalid type header! Expected 0x05, got 0x%02x' %
                             data[0])
        if data[1] != 0:
            raise ValueError('Unexpected NULL value. Lenght should be 0, it '
                             'was %d' % data[1])
        return Null()

    def __bytes__(self):
        return b'\x05\x00'

    def __eq__(self, other):
        return type(self) == type(other)

    def __repr__(self):
        return 'Null()'


class String(Type):

    HEADER = 0x04

    @staticmethod
    def from_bytes(data):
        if data[0] != String.HEADER:
            raise ValueError('Invalid type header! Expected 0x04, got 0x%02x' %
                             data[0])
        length, data = consume_length(data[1:])
        return String(data.decode('ascii'))

    def __init__(self, value):
        self.value = value
        self.length = encode_length(len(value))

    def __bytes__(self):
        return (bytes([String.HEADER, self.length]) +
                self.value.encode('ascii'))

    def __repr__(self):
        return 'String(%r)' % self.value

    def __eq__(self, other):
        return type(self) == type(other) and self.value == other.value


class List(Type):

    HEADER = 0x30

    @staticmethod
    def from_bytes(data):
        if data[0] != List.HEADER:
            raise ValueError('Invalid type header! Expected 0x30, got 0x%02x' %
                             data[0])
        length, content = consume_length(data[1:])
        output = []
        while content:
            value, content = consume(content)
            if value is None:
                break
            output.append(value)
        return List(*output)

    def __init__(self, *items):
        self.items = items

    def __bytes__(self):
        output = [bytes(item) for item in self.items]
        output = b''.join(output)
        length = encode_length(len(output))
        return bytes([List.HEADER, length]) + output

    def __eq__(self, other):
        return type(self) == type(other) and self.items == other.items

    def __repr__(self):
        item_repr = [repr(item) for item in self.items]
        return 'List(%s)' % ', '.join(item_repr)


class Integer:
    HEADER = 0x02

    @staticmethod
    def from_bytes(data):
        if data[0] != Integer.HEADER:
            raise ValueError('Invalid type header! Expected 0x02, got 0x%02x' %
                             data[0])
        length, value = consume_length(data[1:])
        return Integer(int.from_bytes(value, 'big'))

    def __init__(self, value):
        self.value = value

    def __bytes__(self):
        if self.value == 0:
            octets = [0]
        else:
            remainder = self.value
            octets = []
            while remainder:
                octet = remainder & 0b11111111
                remainder = remainder >> 8
                octets.append(octet)
            octets.reverse()
        return bytes([self.HEADER, len(octets)] + octets)

    def __eq__(self, other):
        return type(self) == type(other) and self.value == other.value

    def __repr__(self):
        return 'Integer(%r)' % self.value


class Oid(Type):

    HEADER = 0x06

    @staticmethod
    def decode_large_value(current_char, stream):
        """
        If we encounter a value larger than 127, we have to consume from the
        stram until we encounter a value below 127 and recombine them.

        See: https://msdn.microsoft.com/en-us/library/bb540809(v=vs.85).aspx
        """
        buffer = []
        while current_char > 127:
            buffer.append(current_char ^ 0b10000000)
            current_char = next(stream)
        total = current_char
        for i, digit in enumerate(reversed(buffer)):
            total += digit * 128**(i+1)
        return total

    @staticmethod
    def encode_large_value(value):
        if value <= 127:
            return [value]
        output = [value & 0b1111111]
        value = value >> 7
        while value:
            output.append(value & 0b1111111 | 0b10000000)
            value = value >> 7
        output.reverse()
        return output

    @staticmethod
    def from_bytes(data):
        if data[0] != Oid.HEADER:
            raise ValueError('Invalid type header! Expected 0x02, got 0x%02x' %
                             data[0])

        length, identifiers = consume_length(data[1:])
        # unpack the first byte into first and second sub-identifiers.
        first, second = identifiers[0] // 40, identifiers[0] % 40
        output = [first, second]

        remaining = iter(identifiers[1:])

        for char in remaining:
            # Each node can only contain values from 0-127. Other values need to
            # be combined.
            if char > 127:
                collapsed_value = Oid.decode_large_value(char, remaining)
                output.append(collapsed_value)
                continue
            output.append(char)

        return Oid(*output)

    def __init__(self, *identifiers):
        # If the user hands in an iterable, instead of positional arguments,
        # make sure we unpack it
        if len(identifiers) == 1 and not isinstance(identifiers[0], int):
            identifiers = identifiers[0]

        # The first two bytes are collapsed according to X.690
        # See https://en.wikipedia.org/wiki/X.690#BER_encoding
        first, second, rest = identifiers[0], identifiers[1], identifiers[2:]
        first_output = (40*first) + second

        # Values above 127 need a special encoding. They get split up into
        # multiple positions.
        exploded_high_values = []
        for char in rest:
            if char > 127:
                exploded_high_values.extend(Oid.encode_large_value(char))
            else:
                exploded_high_values.append(char)

        self.identifiers = identifiers
        self.__collapsed_identifiers = [first_output]
        for subidentifier in rest:
            self.__collapsed_identifiers.extend(Oid.encode_large_value(subidentifier))
        self.length = encode_length(len(self.__collapsed_identifiers))

    def __bytes__(self):
        return bytes([self.HEADER, self.length] + self.__collapsed_identifiers)

    def __repr__(self):
        return 'Oid(%r)' % (self.identifiers, )

    def __eq__(self, other):
        return (type(self) == type(other) and
                self.__collapsed_identifiers == other.__collapsed_identifiers)


class Raw(Type):
    """
    This type is used to encapsulate raw bytes. This can be used if no specific
    type exists (yet).
    """

    @staticmethod
    def from_bytes(data):
        octets = [int.from_bytes(char) for char in data]
        return Raw(*octets)

    def __init__(self, *octets):
        self.octets = octets

    def __bytes__(self):
        return bytes(self.octets)


class GetRequest(Type):
    HEADER = 0xa0

    def __init__(self, oid):
        from time import time
        self.request_id = int(time() * 1000000)  # TODO check if this is good enough. My gut tells me "no"!
        self.oid = oid

    def __bytes__(self):
        data = [
            Integer(self.request_id),
            Integer(0),
            Integer(0),
            List(
                List(
                    self.oid,
                    Null(),
                )
            )
        ]
        payload = b''.join([bytes(chunk) for chunk in data])
        output = bytes([self.HEADER, len(payload)]) + payload
        return output


class GetResponse(Type):
    HEADER = 0xa2

    def __init__(self, request_id, value):
        self.request_id = request_id
        self.value = value

    @staticmethod
    def from_bytes(data):
        if data[0] != GetResponse.HEADER:
            raise ValueError('Invalid type header! Expected 0xa2, got 0x%02x' %
                             data[0])
        expected_length, data = consume_length(data[1:])
        if len(data) != expected_length:
            raise ValueError('Corrupt packet: Unexpected length for GET '
                             'response! Expected 0x%02x but got 0x%02x' % (
                                 expected_length, len(data)))
        request_id, data = consume(data)
        error_code, data = consume(data)
        error_index, data = consume(data)
        if error_code.value:
            raise SnmpError('Error packet received!')  # Add detail.
        values, data = consume(data)
        return GetResponse(
            request_id,
            values.items[0].items[1]
        )

    def __repr__(self):
        return 'GetResponse(%r, %r)' % (self.request_id, self.value)

    def __eq__(self, other):
        return (type(other) == type(self) and
                self.request_id == other.request_id and
                self.value == other.value)
