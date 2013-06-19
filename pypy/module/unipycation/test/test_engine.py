import pypy.module.unipycation.engine as eng

class AppTestEngine(object):
    spaceconfig = dict(usemodules=('unipycation',))

    def test_basic(self):
        import unipycation

        e = unipycation.Engine("likes(mac, jazz). likes(bob, jazz). likes(jim, funk).")
        assert isinstance(e, unipycation.Engine)

        res = e.query("likes(X, jazz).")
        assert res["X"] == "mac"

    def test_basic_2(self):
        import unipycation

        e = unipycation.Engine("f(1, a). f(2, b). f(3, c).")
        assert isinstance(e, unipycation.Engine)

        res = e.query("f(X, Y).")
        assert res["X"] == 1

    def test_basic_3(self):
        import unipycation

        e = unipycation.Engine("f(1.23456)")
        assert isinstance(e, unipycation.Engine)

        print(72 * "-")
        res = e.query("f(X)")
        print(res)
        print(72 * "-")
        assert res["X"] == 1.23456

    def test_anonymous(self):
        import unipycation

        e = unipycation.Engine("f(1, a). f(2, b). f(3, c).")
        assert isinstance(e, unipycation.Engine)

        res = e.query("f(_, Y).")
        assert res["Y"] == "a"

    def test_tautology(self):
        import unipycation

        e = unipycation.Engine("f(1).")
        assert isinstance(e, unipycation.Engine)

        res = e.query("f(_)")
        assert res == {}

    def test_false(self):
        import unipycation

        e = unipycation.Engine("f(1).")
        assert isinstance(e, unipycation.Engine)

        res = e.query("f(2).")
        assert res == None
