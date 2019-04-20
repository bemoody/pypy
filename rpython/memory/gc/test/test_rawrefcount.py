import os, py
from rpython.rtyper.lltypesystem import lltype, llmemory, rffi
from rpython.memory.gc.incminimark import IncrementalMiniMarkGC as IncMiniMark
from rpython.memory.gc.test.test_direct import BaseDirectGCTest
from rpython.rlib.rawrefcount import REFCNT_FROM_PYPY, REFCNT_FROM_PYPY_LIGHT

PYOBJ_HDR = IncMiniMark.PYOBJ_HDR
PYOBJ_HDR_PTR = IncMiniMark.PYOBJ_HDR_PTR
RAWREFCOUNT_VISIT = IncMiniMark.RAWREFCOUNT_VISIT
PYOBJ_GC_HDR = IncMiniMark.PYOBJ_GC_HDR
PYOBJ_GC_HDR_PTR = IncMiniMark.PYOBJ_GC_HDR_PTR
RAWREFCOUNT_FINALIZER_MODERN = IncMiniMark.RAWREFCOUNT_FINALIZER_MODERN
RAWREFCOUNT_FINALIZER_LEGACY = IncMiniMark.RAWREFCOUNT_FINALIZER_LEGACY
RAWREFCOUNT_FINALIZER_NONE = IncMiniMark.RAWREFCOUNT_FINALIZER_NONE

S = lltype.GcForwardReference()
S.become(lltype.GcStruct('S',
                         ('x', lltype.Signed),
                         ('prev', lltype.Ptr(S)),
                         ('next', lltype.Ptr(S))))


class TestRawRefCount(BaseDirectGCTest):
    GCClass = IncMiniMark

    def setup_method(self, method):
        BaseDirectGCTest.setup_method(self, method)

        self.trigger = []
        self.gcobjs = []
        self.pyobjs = []
        self.pyobj_refs = []
        self.pyobj_weakrefs = []
        self.pyobj_finalizer = {}
        self.pyobj_finalized = {}
        self.pyobj_resurrect = {}
        self.pyobj_delete = {}
        self.is_pygc = []

        def rawrefcount_tp_traverse(obj, callback, args):
            refs = self.pyobj_refs[self.pyobjs.index(obj)]
            weakrefs = self.pyobj_weakrefs[self.pyobjs.index(obj)]
            for ref in refs:
                callback(ref, args)
            for weakref in weakrefs:
                callback(weakref.r, args)

        def rawrefcount_gc_as_pyobj(gc):
            index = self.gcobjs.index(gc)
            if self.is_pygc[index]:
                return self.pyobjs[index]
            else:
                assert False

        def rawrefcount_pyobj_as_gc(pyobj):
            index = self.pyobjs.index(pyobj)
            if self.is_pygc[index]:
                return self.gcobjs[index]
            else:
                return lltype.nullptr(PYOBJ_GC_HDR)

        def rawrefcount_finalizer_type(gc):
            pyobj = self.pyobjs[self.gcobjs.index(gc)]
            if pyobj in self.pyobjs and \
                    self.pyobj_finalizer.has_key(self.pyobjs.index(pyobj)):
                # TODO: improve test, so that NONE is returned, if finalizer
                #       has already been called (only for modern)
                return self.pyobj_finalizer[self.pyobjs.index(pyobj)]
            else:
                return RAWREFCOUNT_FINALIZER_NONE

        def rawrefcount_clear_wr(gc):
            cleared = False
            for weakrefs in self.pyobj_weakrefs:
                for weakref in weakrefs:
                    if gc._obj.container == weakref.p._obj:
                        weakref.callback_cleared = True
                        cleared = True

        self.pyobj_list = lltype.malloc(PYOBJ_GC_HDR_PTR.TO, flavor='raw',
                                        immortal=True)
        self.pyobj_list.c_gc_next = self.pyobj_list
        self.pyobj_list.c_gc_prev = self.pyobj_list
        self.gc.rawrefcount_init(lambda: self.trigger.append(1),
                                 rawrefcount_tp_traverse,
                                 llmemory.cast_ptr_to_adr(self.pyobj_list),
                                 rawrefcount_gc_as_pyobj,
                                 rawrefcount_pyobj_as_gc,
                                 rawrefcount_finalizer_type,
                                 rawrefcount_clear_wr)

    def _collect(self, major, expected_trigger=0):
        if major:
            self.gc.collect()
        else:
            self.gc._minor_collection()
        count1 = len(self.trigger)
        self.gc.rrc_invoke_callback()
        count2 = len(self.trigger)
        # TODO: fix assertion
        # assert count2 - count1 == expected_trigger

    def _rawrefcount_addref(self, pyobj_from, pyobj_to):
        refs = self.pyobj_refs[self.pyobjs.index(pyobj_from)]
        refs.append(pyobj_to)
        pyobj_to.c_ob_refcnt += 1

    def _rawrefcount_addweakref(self, pyobj_from, weakref):
        refs = self.pyobj_weakrefs[self.pyobjs.index(pyobj_from)]
        refs.append(weakref)
        weakref.r.c_ob_refcnt += 1

    def _rawrefcount_add_resurrect(self, pyobj_source, pyobj_target):
        refs = self.pyobj_resurrect[self.pyobjs.index(pyobj_source)] = []
        refs.append(pyobj_target)

    def _rawrefcount_add_delete(self, pyobj_source, pyobj_target):
        refs = self.pyobj_delete[self.pyobjs.index(pyobj_source)] = []
        refs.append(pyobj_target)

    def _rawrefcount_pypyobj(self, intval, rooted=False, create_old=True):
        p1 = self.malloc(S)
        p1.x = intval

        if create_old:
            self.stackroots.append(p1)
            self._collect(major=False)
            p1 = self.stackroots.pop()
        if rooted:
            self.stackroots.append(p1)
        p1ref = lltype.cast_opaque_ptr(llmemory.GCREF, p1)

        def check_alive():
            p1 = lltype.cast_opaque_ptr(lltype.Ptr(S), p1ref)
            assert p1.x == intval

        return p1, p1ref, check_alive

    def _rawrefcount_pyobj(self, create_immortal=False, is_gc=True):
        r1 = lltype.malloc(PYOBJ_HDR, flavor='raw',
                           immortal=create_immortal)
        r1.c_ob_refcnt = 0
        r1.c_ob_pypy_link = 0
        r1addr = llmemory.cast_ptr_to_adr(r1)

        if is_gc:
            r1gc = lltype.malloc(PYOBJ_GC_HDR, flavor='raw',
                                 immortal=True)
            r1gc.c_gc_next = self.pyobj_list
            r1gc.c_gc_prev = self.pyobj_list.c_gc_prev
            r1gc.c_gc_prev.c_gc_next = r1gc
            self.pyobj_list.c_gc_prev = r1gc
            self.gcobjs.append(r1gc)

        self.pyobjs.append(r1)
        self.is_pygc.append(is_gc)
        self.pyobj_refs.append([])
        self.pyobj_weakrefs.append([])

        def check_alive(extra_refcount):
            assert r1.c_ob_refcnt == extra_refcount

        return r1, r1addr, check_alive

    def _rawrefcount_pair(self, intval, is_light=False, is_pyobj=False,
                          create_old=False, create_immortal=False,
                          rooted=False, force_external=False, is_gc=True):
        if is_light:
            rc = REFCNT_FROM_PYPY_LIGHT
        else:
            rc = REFCNT_FROM_PYPY

        if create_immortal:
            p1 = lltype.malloc(S, immortal=True)
        else:
            saved = self.gc.nonlarge_max
            try:
                if force_external:
                    self.gc.nonlarge_max = 1
                p1 = self.malloc(S)
            finally:
                self.gc.nonlarge_max = saved
        p1.x = intval
        if create_immortal:
            self.consider_constant(p1)
        elif create_old:
            self.stackroots.append(p1)
            self._collect(major=False)
            p1 = self.stackroots.pop()
        if rooted:
            self.stackroots.append(p1)
        p1ref = lltype.cast_opaque_ptr(llmemory.GCREF, p1)
        r1 = lltype.malloc(PYOBJ_HDR, flavor='raw',
                           immortal=create_immortal)
        r1.c_ob_refcnt = rc
        r1.c_ob_pypy_link = 0
        r1addr = llmemory.cast_ptr_to_adr(r1)

        if is_gc:
            r1gc = lltype.malloc(PYOBJ_GC_HDR, flavor='raw',
                                 immortal=True)
            r1gc.c_gc_next = self.pyobj_list
            r1gc.c_gc_prev = self.pyobj_list.c_gc_prev
            r1gc.c_gc_prev.c_gc_next = r1gc
            self.pyobj_list.c_gc_prev = r1gc
            self.gcobjs.append(r1gc)

        self.pyobjs.append(r1)
        self.is_pygc.append(is_gc)
        self.pyobj_refs.append([])
        self.pyobj_weakrefs.append([])

        if is_pyobj:
            assert not is_light
            self.gc.rawrefcount_create_link_pyobj(p1ref, r1addr)
        else:
            self.gc.rawrefcount_create_link_pypy(p1ref, r1addr)
        assert r1.c_ob_refcnt == rc
        assert r1.c_ob_pypy_link != 0

        def check_alive(extra_refcount):
            assert r1.c_ob_refcnt == rc + extra_refcount
            assert r1.c_ob_pypy_link != 0
            p1ref = self.gc.rawrefcount_to_obj(r1addr)
            p1 = lltype.cast_opaque_ptr(lltype.Ptr(S), p1ref)
            assert p1.x == intval
            if not is_pyobj:
                assert self.gc.rawrefcount_from_obj(p1ref) == r1addr
            else:
                assert self.gc.rawrefcount_from_obj(p1ref) == llmemory.NULL
            return p1
        return p1, p1ref, r1, r1addr, check_alive

    def test_rawrefcount_objects_basic(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=True, create_old=old))
        p2 = self.malloc(S)
        p2.x = 84
        p2ref = lltype.cast_opaque_ptr(llmemory.GCREF, p2)
        r2 = lltype.malloc(PYOBJ_HDR_PTR.TO, flavor='raw')
        r2.c_ob_refcnt = 1
        r2.c_ob_pypy_link = 0
        r2addr = llmemory.cast_ptr_to_adr(r2)
        # p2 and r2 are not linked
        assert r1.c_ob_pypy_link != 0
        assert r2.c_ob_pypy_link == 0
        assert self.gc.rawrefcount_from_obj(p1ref) == r1addr
        assert self.gc.rawrefcount_from_obj(p2ref) == llmemory.NULL
        assert self.gc.rawrefcount_to_obj(r1addr) == p1ref
        assert self.gc.rawrefcount_to_obj(r2addr) == lltype.nullptr(
            llmemory.GCREF.TO)
        lltype.free(r1, flavor='raw')
        lltype.free(r2, flavor='raw')

    def test_rawrefcount_objects_collection_survives_from_raw(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=True, create_old=old))
        check_alive(0)
        r1.c_ob_refcnt += 1
        self._collect(major=False)
        check_alive(+1)
        self._collect(major=True)
        check_alive(+1)
        r1.c_ob_refcnt -= 1
        self._collect(major=False)
        p1 = check_alive(0)
        self._collect(major=True)
        py.test.raises(RuntimeError, "r1.c_ob_refcnt")    # dead
        py.test.raises(RuntimeError, "p1.x")            # dead
        self.gc.check_no_more_rawrefcount_state()
        # TODO: fix assertion
        # assert self.trigger == []
        assert self.gc.rawrefcount_next_dead() == llmemory.NULL

    def test_rawrefcount_dies_quickly(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=True, create_old=old))
        check_alive(0)
        self._collect(major=False)
        if old:
            check_alive(0)
            self._collect(major=True)
        py.test.raises(RuntimeError, "r1.c_ob_refcnt")    # dead
        py.test.raises(RuntimeError, "p1.x")            # dead
        self.gc.check_no_more_rawrefcount_state()

    def test_rawrefcount_objects_collection_survives_from_obj(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=True, create_old=old))
        check_alive(0)
        self.stackroots.append(p1)
        self._collect(major=False)
        check_alive(0)
        self._collect(major=True)
        check_alive(0)
        p1 = self.stackroots.pop()
        self._collect(major=False)
        check_alive(0)
        assert p1.x == 42
        self._collect(major=True)
        py.test.raises(RuntimeError, "r1.c_ob_refcnt")    # dead
        py.test.raises(RuntimeError, "p1.x")            # dead
        self.gc.check_no_more_rawrefcount_state()

    def test_rawrefcount_objects_basic_old(self):
        self.test_rawrefcount_objects_basic(old=True)
    def test_rawrefcount_objects_collection_survives_from_raw_old(self):
        self.test_rawrefcount_objects_collection_survives_from_raw(old=True)
    def test_rawrefcount_dies_quickly_old(self):
        self.test_rawrefcount_dies_quickly(old=True)
    def test_rawrefcount_objects_collection_survives_from_obj_old(self):
        self.test_rawrefcount_objects_collection_survives_from_obj(old=True)

    def test_pypy_nonlight_survives_from_raw(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=False, create_old=old))
        check_alive(0)
        r1.c_ob_refcnt += 1
        self._collect(major=False)
        check_alive(+1)
        self._collect(major=True)
        check_alive(+1)
        r1.c_ob_refcnt -= 1
        self._collect(major=False)
        p1 = check_alive(0)
        self._collect(major=True, expected_trigger=1)
        py.test.raises(RuntimeError, "p1.x")            # dead
        assert r1.c_ob_refcnt == 1       # in the pending list
        assert r1.c_ob_pypy_link == 0
        assert self.gc.rawrefcount_next_dead() == r1addr
        assert self.gc.rawrefcount_next_dead() == llmemory.NULL
        assert self.gc.rawrefcount_next_dead() == llmemory.NULL
        self.gc.check_no_more_rawrefcount_state()
        lltype.free(r1, flavor='raw')

    def test_pypy_nonlight_survives_from_obj(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=False, create_old=old))
        check_alive(0)
        self.stackroots.append(p1)
        self._collect(major=False)
        check_alive(0)
        self._collect(major=True)
        check_alive(0)
        p1 = self.stackroots.pop()
        self._collect(major=False)
        check_alive(0)
        assert p1.x == 42
        self._collect(major=True, expected_trigger=1)
        py.test.raises(RuntimeError, "p1.x")            # dead
        assert r1.c_ob_refcnt == 1
        assert r1.c_ob_pypy_link == 0
        assert self.gc.rawrefcount_next_dead() == r1addr
        self.gc.check_no_more_rawrefcount_state()
        lltype.free(r1, flavor='raw')

    def test_pypy_nonlight_dies_quickly(self, old=False):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_light=False, create_old=old))
        check_alive(0)
        if old:
            self._collect(major=False)
            check_alive(0)
            self._collect(major=True, expected_trigger=1)
        else:
            self._collect(major=False, expected_trigger=1)
        py.test.raises(RuntimeError, "p1.x")            # dead
        assert r1.c_ob_refcnt == 1
        assert r1.c_ob_pypy_link == 0
        assert self.gc.rawrefcount_next_dead() == r1addr
        self.gc.check_no_more_rawrefcount_state()
        lltype.free(r1, flavor='raw')

    def test_pypy_nonlight_survives_from_raw_old(self):
        self.test_pypy_nonlight_survives_from_raw(old=True)
    def test_pypy_nonlight_survives_from_obj_old(self):
        self.test_pypy_nonlight_survives_from_obj(old=True)
    def test_pypy_nonlight_dies_quickly_old(self):
        self.test_pypy_nonlight_dies_quickly(old=True)

    @py.test.mark.parametrize('external', [False, True])
    def test_pyobject_pypy_link_dies_on_minor_collection(self, external):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_pyobj=True, force_external=external))
        check_alive(0)
        r1.c_ob_refcnt += 1            # the pyobject is kept alive
        self._collect(major=False)
        assert r1.c_ob_refcnt == 1     # refcnt dropped to 1
        assert r1.c_ob_pypy_link == 0  # detached
        self.gc.check_no_more_rawrefcount_state()
        lltype.free(r1, flavor='raw')

    @py.test.mark.parametrize('old,external', [
        (False, False), (True, False), (False, True)])
    def test_pyobject_dies(self, old, external):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_pyobj=True, create_old=old,
                                   force_external=external))
        check_alive(0)
        if old:
            self._collect(major=False)
            check_alive(0)
            self._collect(major=True, expected_trigger=1)
        else:
            self._collect(major=False, expected_trigger=1)
        assert r1.c_ob_refcnt == 1     # refcnt 1, in the pending list
        assert r1.c_ob_pypy_link == 0  # detached
        assert self.gc.rawrefcount_next_dead() == r1addr
        self.gc.check_no_more_rawrefcount_state()
        lltype.free(r1, flavor='raw')

    @py.test.mark.parametrize('old,external', [
        (False, False), (True, False), (False, True)])
    def test_pyobject_survives_from_obj(self, old, external):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, is_pyobj=True, create_old=old,
                                   force_external=external))
        check_alive(0)
        self.stackroots.append(p1)
        self._collect(major=False)
        check_alive(0)
        self._collect(major=True)
        check_alive(0)
        p1 = self.stackroots.pop()
        self._collect(major=False)
        check_alive(0)
        assert p1.x == 42
        # TODO: fix assertion
        # assert self.trigger == []
        self._collect(major=True, expected_trigger=1)
        py.test.raises(RuntimeError, "p1.x")            # dead
        assert r1.c_ob_refcnt == 1
        assert r1.c_ob_pypy_link == 0
        assert self.gc.rawrefcount_next_dead() == r1addr
        self.gc.check_no_more_rawrefcount_state()
        lltype.free(r1, flavor='raw')

    def test_pyobject_attached_to_prebuilt_obj(self):
        p1, p1ref, r1, r1addr, check_alive = (
            self._rawrefcount_pair(42, create_immortal=True))
        check_alive(0)
        self._collect(major=True)
        check_alive(0)

    dot_dir = os.path.join(os.path.realpath(os.path.dirname(__file__)), "dot")
    dot_files = [file for file in os.listdir(dot_dir) if file.endswith(".dot")]
    dot_files.sort()

    @py.test.mark.dont_track_allocations('intentionally keep objects alive, '
                                         'because we do the checks ourselves')
    @py.test.mark.parametrize("file", dot_files)
    def test_dots(self, file):
        from rpython.memory.gc.test.dot import pydot

        class Node:
            def __init__(self, info):
                self.info = info

        class CPythonNode(Node):
            def __init__(self, r, raddr, check_alive, info):
                self.r = r
                self.raddr = raddr
                self.check_alive = check_alive
                self.info = info

        class PyPyNode(Node):
            def __init__(self, p, pref, check_alive, info):
                self.p = p
                self.pref = pref
                self.check_alive = check_alive
                self.info = info

        class BorderNode(Node):
            def __init__(self, p, pref, r, raddr, check_alive, info):
                self.p = p
                self.pref = pref
                self.r = r
                self.raddr = raddr
                self.check_alive = check_alive
                self.info = info

        class NodeInfo:
            def __init__(self, type, alive, ext_refcnt, finalizer, resurrect,
                         delete, garbage):
                self.type = type
                self.alive = alive
                self.ext_refcnt = ext_refcnt
                self.finalizer = finalizer
                self.resurrect = resurrect
                self.delete = delete
                self.garbage = garbage

        class WeakrefNode(BorderNode):
            def __init__(self, p, pref, r, raddr, check_alive, info, r_dest,
                         callback, clear_callback):
                self.p = p
                self.pref = pref
                self.r = r
                self.raddr = raddr
                self.check_alive = check_alive
                self.info = info
                self.r_dest = r_dest
                self.callback = callback
                self.clear_callback = clear_callback
                self.callback_cleared = False

        path = os.path.join(self.dot_dir, file)
        g = pydot.graph_from_dot_file(path)[0]
        nodes = {}

        # create objects from graph (always create old to prevent moving)
        finalizers = False
        i = 0
        for n in g.get_nodes():
            name = n.get_name()
            attr = n.obj_dict['attributes']
            type = attr['type']
            alive = attr['alive'] == "y"
            rooted = attr['rooted'] == "y" if 'rooted' in attr else False
            ext_refcnt = int(attr['ext_refcnt']) if 'ext_refcnt' in attr else 0
            finalizer = attr['finalizer'] if 'finalizer' in attr else None
            if finalizer == "modern":
                finalizers = True
            resurrect = attr['resurrect'] if 'resurrect' in attr else None
            delete = attr['delete'] if 'delete' in attr else None
            garbage = True if 'garbage' in attr else False
            info = NodeInfo(type, alive, ext_refcnt, finalizer, resurrect,
                            delete, garbage)
            if type == "C":
                r, raddr, check_alive = self._rawrefcount_pyobj()
                r.c_ob_refcnt += ext_refcnt
                nodes[name] = CPythonNode(r, raddr, check_alive, info)
            elif type == "P":
                p, pref, check_alive = \
                    self._rawrefcount_pypyobj(42 + i, rooted=rooted,
                                              create_old=True)
                nodes[name] = PyPyNode(p, pref, check_alive, info)
                i += 1
            elif type == "B":
                p, pref, r, raddr, check_alive =\
                    self._rawrefcount_pair(42 + i, rooted=rooted,
                                           create_old=True)
                r.c_ob_refcnt += ext_refcnt
                nodes[name] = BorderNode(p, pref, r, raddr, check_alive, info)
                i += 1

        # add references between objects from graph
        for e in g.get_edges():
            source = nodes[e.get_source()]
            dest = nodes[e.get_destination()]
            attr = e.obj_dict['attributes']
            weakref = attr['weakref'] == "y" if 'weakref' in attr else False
            callback = attr['callback'] == "y" if 'callback' in attr else False
            clear_callback = attr['clear_callback'] == "y" \
                if 'clear_callback' in attr else False
            if source.info.type == "C" or dest.info.type == "C":
                if weakref:
                    # only weakrefs from C objects supported in tests
                    assert source.info.type == "C"
                    p, pref, r, raddr, check_alive = \
                        self._rawrefcount_pair(42 + i, rooted=False,
                                               create_old=True, is_gc=False)
                    weakref = WeakrefNode(p, pref, r, raddr, check_alive, info,
                                          dest.r, callback, clear_callback)
                    self._rawrefcount_addweakref(source.r, weakref)
                    i += 1
                else:
                    self._rawrefcount_addref(source.r, dest.r)
                    if source.info.alive:
                        dest.info.ext_refcnt += 1
            elif source.info.type == "P" or dest.info.type == "P":
                if llmemory.cast_ptr_to_adr(source.p.next) == llmemory.NULL:
                    source.p.next = dest.p
                elif llmemory.cast_ptr_to_adr(source.p.prev) == llmemory.NULL:
                    source.p.prev = dest.p
                else:
                    assert False # only 2 refs supported from pypy obj in tests

        # add finalizers
        for name in nodes:
            n = nodes[name]
            if hasattr(n, "r"):
                index = self.pyobjs.index(n.r)
                resurrect = n.info.resurrect
                delete = n.info.delete
                if n.info.finalizer == "modern":
                    self.pyobj_finalizer[index] = RAWREFCOUNT_FINALIZER_MODERN
                    if resurrect is not None:
                        self._rawrefcount_add_resurrect(n.r,
                                                        nodes[resurrect].r)
                        nodes[resurrect].info.ext_refcnt += 1
                    if delete is not None:
                        self._rawrefcount_add_delete(n.r, nodes[delete].r)
                elif n.info.finalizer == "legacy":
                    self.pyobj_finalizer[index] = RAWREFCOUNT_FINALIZER_LEGACY
                else:
                    self.pyobj_finalizer[index] = RAWREFCOUNT_FINALIZER_NONE

        # quick self check, if traverse works properly
        dests_by_source = {}
        for e in g.get_edges():
            source = nodes[e.get_source()]
            dest = nodes[e.get_destination()]
            attr = e.obj_dict['attributes']
            weakref = attr['weakref'] == "y" if 'weakref' in attr else False
            if source.info.type == "C" or dest.info.type == "C":
                if not dests_by_source.has_key(source):
                    dests_by_source[source] = []
                if weakref:
                    wrs = self.pyobj_weakrefs[self.pyobjs.index(source.r)]
                    # currently only one weakref supported
                    dests_by_source[source].append(wrs[0].r)
                else:
                    dests_by_source[source].append(dest.r)
        for source in dests_by_source:
            dests_target = dests_by_source[source]
            def append(pyobj, ignore):
                dests_target.remove(pyobj)
            self.gc.rrc_tp_traverse(source.r, append, None)
            assert len(dests_target) == 0

        garbage_pypy = []
        garbage_pyobj = []
        def cleanup():
            # do cleanup after collection (clear all dead pyobjects)
            def finalize_modern(pyobj):
                index = self.pyobjs.index(pyobj)
                if not self.pyobj_finalizer.has_key(index) or \
                    self.pyobj_finalizer[index] != \
                        RAWREFCOUNT_FINALIZER_MODERN:
                    return
                if self.pyobj_finalized.has_key(index):
                    return
                self.pyobj_finalized[index] = True
                if self.pyobj_resurrect.has_key(index):
                    resurrect = self.pyobj_resurrect[index]
                    for r in resurrect:
                        r.c_ob_refcnt += 1
                if self.pyobj_delete.has_key(index):
                    delete = self.pyobj_delete[index]
                    for r in delete:
                        self.pyobj_refs[index].remove(r)
                        decref(r, None)

            def decref_children(pyobj):
                self.gc.rrc_tp_traverse(pyobj, decref, None)

            def decref(pyobj, ignore):
                pyobj.c_ob_refcnt -= 1
                if pyobj.c_ob_refcnt == 0:
                    finalize_modern(pyobj)
                if pyobj.c_ob_refcnt == 0:
                    gchdr = self.gc.rrc_pyobj_as_gc(pyobj)
                    next = gchdr.c_gc_next
                    next.c_gc_prev = gchdr.c_gc_prev
                    gchdr.c_gc_prev.c_gc_next = next
                    decref_children(pyobj)
                    self.pyobjs[self.pyobjs.index(pyobj)] = \
                        lltype.nullptr(PYOBJ_HDR_PTR.TO)
                    lltype.free(pyobj, flavor='raw')

            next_dead = self.gc.rawrefcount_next_dead()
            while next_dead <> llmemory.NULL:
                pyobj = llmemory.cast_adr_to_ptr(next_dead,
                                                 self.gc.PYOBJ_HDR_PTR)
                decref(pyobj, None)
                next_dead = self.gc.rawrefcount_next_dead()

            next = self.gc.rawrefcount_next_cyclic_isolate()
            while next <> llmemory.NULL:
                pyobj = llmemory.cast_adr_to_ptr(next,
                                                 self.gc.PYOBJ_HDR_PTR)
                pyobj.c_ob_refcnt += 1
                finalize_modern(pyobj)
                decref(pyobj, None)
                next = self.gc.rawrefcount_next_cyclic_isolate()

            next_dead = self.gc.rawrefcount_cyclic_garbage_head()
            while next_dead <> llmemory.NULL:
                pyobj = llmemory.cast_adr_to_ptr(next_dead,
                                                 self.gc.PYOBJ_HDR_PTR)
                pyobj.c_ob_refcnt += 1

                def clear(pyobj_to, pyobj_from):
                    refs = self.pyobj_refs[self.pyobjs.index(pyobj_from)]
                    weakrefs = self.pyobj_weakrefs[self.pyobjs.index(pyobj_from)]
                    if pyobj_to in refs:
                        refs.remove(pyobj_to)
                        decref(pyobj_to, None)
                    else:
                        pass # weakref

                self.gc.rrc_tp_traverse(pyobj, clear, pyobj)

                decref(pyobj, None)

                curr = llmemory.cast_adr_to_int(next_dead)
                next_dead = self.gc.rawrefcount_cyclic_garbage_head()

                if llmemory.cast_adr_to_int(next_dead) == curr:
                    self.gc.rawrefcount_cyclic_garbage_remove()
                    next_dead = self.gc.rawrefcount_cyclic_garbage_head()

            self.gc.rawrefcount_begin_garbage()
            next_garbage = self.gc.rawrefcount_next_garbage_pypy()
            while next_garbage <> lltype.nullptr(llmemory.GCREF.TO):
                garbage_pypy.append(next_garbage)
                next_garbage = self.gc.rawrefcount_next_garbage_pypy()
            next = self.gc.rawrefcount_next_garbage_pyobj()
            while next <> llmemory.NULL:
                garbage_pyobj.append(next)
                next = self.gc.rawrefcount_next_garbage_pyobj()
            self.gc.rawrefcount_end_garbage()

        # do a collection to find cyclic isolates and clean them, if there are
        # no finalizers
        self.gc.collect()
        self.gc.rrc_invoke_callback()
        if self.trigger <> []:
            cleanup()

        if finalizers:
            # now do another collection, to clean up cyclic trash, if there
            # were finalizers involved
            self.gc.collect()
            self.gc.rrc_invoke_callback()
            if self.trigger <> []:
                cleanup()

        # check livelihood of objects, according to graph
        for name in nodes:
            n = nodes[name]
            if n.info.alive:
                if n.info.type == "P":
                    n.check_alive()
                else:
                    n.check_alive(n.info.ext_refcnt)
            else:
                if n.info.type == "P":
                    py.test.raises(RuntimeError, "n.p.x")  # dead
                else:
                    py.test.raises(RuntimeError, "n.r.c_ob_refcnt")  # dead

        # check if all callbacks from weakrefs from cyclic garbage structures,
        # which should not be called because they could ressurrect dead
        # objects, have been cleared and no other callbacks were cleared; see:
        # https://github.com/python/cpython/blob/master/Modules/gc_weakref.txt
        for weakrefs in self.pyobj_weakrefs:
            for weakref in weakrefs:
                assert weakref.callback_cleared == weakref.clear_callback

        # check if unreachable objects in cyclic structures with legacy
        # finalizers and all otherwise unreachable objects reachable from them
        # have been added to the garbage list
        for name in nodes:
            n = nodes[name]
            garbage = n.info.garbage
            if n.info.alive:
                if n.info.type == "C":
                    assert garbage != (n.raddr not in garbage_pyobj), \
                        "PyObject should " + ("" if garbage else "not ") + \
                        "be in garbage"
                else:
                    assert garbage != (n.pref not in garbage_pypy), \
                        "Object should " + ("" if garbage else "not ") + \
                        "be in garbage"
            else:
                assert not garbage, "Object is dead, but should be in garbage"
