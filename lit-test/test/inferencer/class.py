# RUN: %python -m artiq.compiler.testbench.inferencer %s >%t
# RUN: OutputCheck %s --file-to-check=%t

class c:
    a = 1
    def f():
        pass
    def m(self):
        pass

# CHECK-L: c:<constructor c {a: int(width='a), f: ()->NoneType, m: (self:c)->NoneType}>
c
# CHECK-L: .a:int(width='a)
c.a
# CHECK-L: .f:()->NoneType
c.f

# CHECK-L: .m:method(fn=(self:c)->NoneType, self=c)
c().m()