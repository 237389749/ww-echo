from ctypes import c_uint32, c_void_p

from ww_engine import rotypes
from ww_engine.rotypes.idldsl import define_winrt_com_method, _non_activatable_init, _static_method, runtimeclass, GUID
from ww_engine.rotypes.inspectable import IInspectable


@GUID('320B7E22-3CB0-4CDF-8663-1D28910065EB')
class ICryptographicBufferStatics(IInspectable):
    pass


class CryptographicBuffer(runtimeclass):
    __init__ = _non_activatable_init
    CreateFromByteArray = _static_method(ICryptographicBufferStatics, 'CreateFromByteArray')


define_winrt_com_method(ICryptographicBufferStatics, 'CreateFromByteArray', c_uint32, c_void_p,
                        retval=rotypes.Windows.Storage.Streams.IBuffer, vtbl=9)
