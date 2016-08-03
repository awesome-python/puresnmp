"""
SMI Types / Structure types which are not defined in ASN.1
"""

from .exc import SnmpError
from .x690.types import Integer, Type, Sequence, Null, pop_tlv, encode_length
from .x690.util import TypeInfo


class IpAddress(Integer):
    TYPECLASS = TypeInfo.APPLICATION
    TAG = 0x00


class Counter(Integer):
    TYPECLASS = TypeInfo.APPLICATION
    TAG = 0x01


class Gauge(Integer):
    TYPECLASS = TypeInfo.APPLICATION
    TAG = 0x02


class TimeTicks(Integer):
    TYPECLASS = TypeInfo.APPLICATION
    TAG = 0x03


class Opaque(Integer):
    TYPECLASS = TypeInfo.APPLICATION
    TAG = 0x04


class NsapAddress(Integer):
    TYPECLASS = TypeInfo.APPLICATION
    TAG = 0x05


# --- Requests / Responses

class RequestResponsePacket(Type):

    @classmethod
    def validate(cls, data):
        tinfo = TypeInfo.from_bytes(data[0])
        if tinfo.cls != TypeInfo.CONTEXT or tinfo.tag != cls.TAG:
            raise ValueError(
                'Invalid type header! '
                'Expected "context" tag with ID 0x%02x, '
                'got ID 0x%02x' % (cls.TAG, data[0]))


class GetRequest(RequestResponsePacket):
    TYPECLASS, _, TAG = TypeInfo.from_bytes(0xa0)

    def __init__(self, oid, request_id):
        self.request_id = request_id
        self.oid = oid

    def __bytes__(self):
        data = [
            Integer(self.request_id),
            Integer(0),
            Integer(0),
            Sequence(
                Sequence(
                    self.oid,
                    Null(),
                )
            )
        ]
        payload = b''.join([bytes(chunk) for chunk in data])

        tinfo = TypeInfo(TypeInfo.CONTEXT, TypeInfo.CONSTRUCTED, self.TAG)
        length = encode_length(len(payload))
        return bytes(tinfo) + length + payload

    def __repr__(self):
        return '%s(%r, %r)' % (
            self.__class__.__name__, self.request_id, self.oid)


class GetResponse(RequestResponsePacket):
    TYPECLASS, _, TAG = TypeInfo.from_bytes(0xa2)

    def __init__(self, request_id, oid, value):
        self.request_id = request_id
        self.oid = oid
        self.value = value

    @classmethod
    def decode(cls, data):
        request_id, data = pop_tlv(data)
        error_code, data = pop_tlv(data)
        error_index, data = pop_tlv(data)
        if error_code.value:
            raise SnmpError('Error packet received!')  # TODO Add detail.
        values, data = pop_tlv(data)

        # TODO the following index fiddling is ugly!
        if len(values.items[0].items) == 1:
            # empty result
            value = None
        else:
            value = values.items[0].items[1]

        return GetResponse(
            request_id,
            values.items[0].items[0],
            value,
        )

    def __repr__(self):
        return 'GetResponse(%r, %r, %r)' % (
            self.request_id, self.oid, self.value)

    def __eq__(self, other):
        return (type(other) == type(self) and
                self.request_id == other.request_id and
                self.oid == other.oid and
                self.value == other.value)


class GetNextRequest(GetRequest):
    TYPECLASS, _, TAG = TypeInfo.from_bytes(0xa1)