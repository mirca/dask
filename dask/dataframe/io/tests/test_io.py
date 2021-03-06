import numpy as np
import pandas as pd
import pandas.util.testing as tm

import pytest
from distutils.version import LooseVersion
from threading import Lock

import threading

import dask.array as da
import dask.dataframe as dd
from dask.dataframe.io.io import _meta_from_array
from dask.delayed import Delayed

from dask.utils import tmpfile
from dask.async import get_sync

from dask.dataframe.utils import assert_eq


####################
# Arrays and BColz #
####################


def test_meta_from_array():
    x = np.array([[1, 2], [3, 4]], dtype=np.int64)
    res = _meta_from_array(x)
    assert isinstance(res, pd.DataFrame)
    assert res[0].dtype == np.int64
    assert res[1].dtype == np.int64
    tm.assert_index_equal(res.columns, pd.Index([0, 1]))

    x = np.array([[1., 2.], [3., 4.]], dtype=np.float64)
    res = _meta_from_array(x, columns=['a', 'b'])
    assert isinstance(res, pd.DataFrame)
    assert res['a'].dtype == np.float64
    assert res['b'].dtype == np.float64
    tm.assert_index_equal(res.columns, pd.Index(['a', 'b']))

    with pytest.raises(ValueError):
        _meta_from_array(x, columns=['a', 'b', 'c'])

    np.random.seed(42)
    x = np.random.rand(201, 2)
    x = dd.from_array(x, chunksize=50, columns=['a', 'b'])
    assert len(x.divisions) == 6   # Should be 5 partitions and the end


def test_meta_from_1darray():
    x = np.array([1., 2., 3.], dtype=np.float64)
    res = _meta_from_array(x)
    assert isinstance(res, pd.Series)
    assert res.dtype == np.float64

    x = np.array([1, 2, 3], dtype=np.object_)
    res = _meta_from_array(x, columns='x')
    assert isinstance(res, pd.Series)
    assert res.name == 'x'
    assert res.dtype == np.object_

    x = np.array([1, 2, 3], dtype=np.object_)
    res = _meta_from_array(x, columns=['x'])
    assert isinstance(res, pd.DataFrame)
    assert res['x'].dtype == np.object_
    tm.assert_index_equal(res.columns, pd.Index(['x']))

    with pytest.raises(ValueError):
        _meta_from_array(x, columns=['a', 'b'])


def test_meta_from_recarray():
    x = np.array([(i, i * 10) for i in range(10)],
                 dtype=[('a', np.float64), ('b', np.int64)])
    res = _meta_from_array(x)
    assert isinstance(res, pd.DataFrame)
    assert res['a'].dtype == np.float64
    assert res['b'].dtype == np.int64
    tm.assert_index_equal(res.columns, pd.Index(['a', 'b']))

    res = _meta_from_array(x, columns=['b', 'a'])
    assert isinstance(res, pd.DataFrame)
    assert res['a'].dtype == np.float64
    assert res['b'].dtype == np.int64
    tm.assert_index_equal(res.columns, pd.Index(['b', 'a']))

    with pytest.raises(ValueError):
        _meta_from_array(x, columns=['a', 'b', 'c'])


def test_from_array():
    x = np.arange(10 * 3).reshape(10, 3)
    d = dd.from_array(x, chunksize=4)
    assert isinstance(d, dd.DataFrame)
    tm.assert_index_equal(d.columns, pd.Index([0, 1, 2]))
    assert d.divisions == (0, 4, 8, 9)
    assert (d.compute().values == x).all()

    d = dd.from_array(x, chunksize=4, columns=list('abc'))
    assert isinstance(d, dd.DataFrame)
    tm.assert_index_equal(d.columns, pd.Index(['a', 'b', 'c']))
    assert d.divisions == (0, 4, 8, 9)
    assert (d.compute().values == x).all()

    with pytest.raises(ValueError):
        dd.from_array(np.ones(shape=(10, 10, 10)))


def test_from_array_with_record_dtype():
    x = np.array([(i, i * 10) for i in range(10)],
                 dtype=[('a', 'i4'), ('b', 'i4')])
    d = dd.from_array(x, chunksize=4)
    assert isinstance(d, dd.DataFrame)
    assert list(d.columns) == ['a', 'b']
    assert d.divisions == (0, 4, 8, 9)

    assert (d.compute().to_records(index=False) == x).all()


def test_from_bcolz_multiple_threads():
    bcolz = pytest.importorskip('bcolz')

    def check():
        t = bcolz.ctable([[1, 2, 3], [1., 2., 3.], ['a', 'b', 'a']],
                         names=['x', 'y', 'a'])
        d = dd.from_bcolz(t, chunksize=2)
        assert d.npartitions == 2
        assert str(d.dtypes['a']) == 'category'
        assert list(d.x.compute(get=get_sync)) == [1, 2, 3]
        assert list(d.a.compute(get=get_sync)) == ['a', 'b', 'a']

        d = dd.from_bcolz(t, chunksize=2, index='x')
        L = list(d.index.compute(get=get_sync))
        assert L == [1, 2, 3] or L == [1, 3, 2]

        # Names
        assert (sorted(dd.from_bcolz(t, chunksize=2).dask) ==
                sorted(dd.from_bcolz(t, chunksize=2).dask))
        assert (sorted(dd.from_bcolz(t, chunksize=2).dask) !=
                sorted(dd.from_bcolz(t, chunksize=3).dask))

    threads = []
    for i in range(5):
        thread = threading.Thread(target=check)
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()


def test_from_bcolz():
    bcolz = pytest.importorskip('bcolz')

    t = bcolz.ctable([[1, 2, 3], [1., 2., 3.], ['a', 'b', 'a']],
                     names=['x', 'y', 'a'])
    d = dd.from_bcolz(t, chunksize=2)
    assert d.npartitions == 2
    assert str(d.dtypes['a']) == 'category'
    assert list(d.x.compute(get=get_sync)) == [1, 2, 3]
    assert list(d.a.compute(get=get_sync)) == ['a', 'b', 'a']
    L = list(d.index.compute(get=get_sync))
    assert L == [0, 1, 2]

    d = dd.from_bcolz(t, chunksize=2, index='x')
    L = list(d.index.compute(get=get_sync))
    assert L == [1, 2, 3] or L == [1, 3, 2]

    # Names
    assert (sorted(dd.from_bcolz(t, chunksize=2).dask) ==
            sorted(dd.from_bcolz(t, chunksize=2).dask))
    assert (sorted(dd.from_bcolz(t, chunksize=2).dask) !=
            sorted(dd.from_bcolz(t, chunksize=3).dask))

    dsk = dd.from_bcolz(t, chunksize=3).dask

    t.append((4, 4., 'b'))
    t.flush()

    assert (sorted(dd.from_bcolz(t, chunksize=2).dask) !=
            sorted(dsk))


def test_from_bcolz_no_lock():
    bcolz = pytest.importorskip('bcolz')
    locktype = type(Lock())

    t = bcolz.ctable([[1, 2, 3], [1., 2., 3.], ['a', 'b', 'a']],
                     names=['x', 'y', 'a'], chunklen=2)
    a = dd.from_bcolz(t, chunksize=2)
    b = dd.from_bcolz(t, chunksize=2, lock=True)
    c = dd.from_bcolz(t, chunksize=2, lock=False)
    assert_eq(a, b)
    assert_eq(a, c)

    assert not any(isinstance(item, locktype)
                   for v in c.dask.values()
                   for item in v)


def test_from_bcolz_filename():
    bcolz = pytest.importorskip('bcolz')

    with tmpfile('.bcolz') as fn:
        t = bcolz.ctable([[1, 2, 3], [1., 2., 3.], ['a', 'b', 'a']],
                         names=['x', 'y', 'a'],
                         rootdir=fn)
        t.flush()

        d = dd.from_bcolz(fn, chunksize=2)
        assert list(d.x.compute()) == [1, 2, 3]


def test_from_bcolz_column_order():
    bcolz = pytest.importorskip('bcolz')

    t = bcolz.ctable([[1, 2, 3], [1., 2., 3.], ['a', 'b', 'a']],
                     names=['x', 'y', 'a'])
    df = dd.from_bcolz(t, chunksize=2)
    assert list(df.loc[0].compute().columns) == ['x', 'y', 'a']


def test_from_pandas_dataframe():
    a = list('aaaaaaabbbbbbbbccccccc')
    df = pd.DataFrame(dict(a=a, b=np.random.randn(len(a))),
                      index=pd.date_range(start='20120101', periods=len(a)))
    ddf = dd.from_pandas(df, 3)
    assert len(ddf.dask) == 3
    assert len(ddf.divisions) == len(ddf.dask) + 1
    assert isinstance(ddf.divisions[0], type(df.index[0]))
    tm.assert_frame_equal(df, ddf.compute())
    ddf = dd.from_pandas(df, chunksize=8)
    msg = 'Exactly one of npartitions and chunksize must be specified.'
    with tm.assertRaisesRegexp(ValueError, msg):
        dd.from_pandas(df, npartitions=2, chunksize=2)
    with tm.assertRaisesRegexp((ValueError, AssertionError), msg):
        dd.from_pandas(df)
    assert len(ddf.dask) == 3
    assert len(ddf.divisions) == len(ddf.dask) + 1
    assert isinstance(ddf.divisions[0], type(df.index[0]))
    tm.assert_frame_equal(df, ddf.compute())


def test_from_pandas_small():
    df = pd.DataFrame({'x': [1, 2, 3]})
    for i in [1, 2, 30]:
        a = dd.from_pandas(df, i)
        assert len(a.compute()) == 3
        assert a.divisions[0] == 0
        assert a.divisions[-1] == 2

        a = dd.from_pandas(df, chunksize=i)
        assert len(a.compute()) == 3
        assert a.divisions[0] == 0
        assert a.divisions[-1] == 2

    for sort in [True, False]:
        for i in [0, 2]:
            df = pd.DataFrame({'x': [0] * i})
            ddf = dd.from_pandas(df, npartitions=5, sort=sort)
            assert_eq(df, ddf)

            s = pd.Series([0] * i, name='x')
            ds = dd.from_pandas(s, npartitions=5, sort=sort)
            assert_eq(s, ds)


@pytest.mark.xfail(reason="")
def test_from_pandas_npartitions_is_accurate():
    df = pd.DataFrame({'x': [1, 2, 3, 4, 5, 6], 'y': list('abdabd')},
                      index=[10, 20, 30, 40, 50, 60])
    for n in [1, 2, 4, 5]:
        assert dd.from_pandas(df, npartitions=n).npartitions == n


def test_from_pandas_series():
    n = 20
    s = pd.Series(np.random.randn(n),
                  index=pd.date_range(start='20120101', periods=n))
    ds = dd.from_pandas(s, 3)
    assert len(ds.dask) == 3
    assert len(ds.divisions) == len(ds.dask) + 1
    assert isinstance(ds.divisions[0], type(s.index[0]))
    tm.assert_series_equal(s, ds.compute())

    ds = dd.from_pandas(s, chunksize=8)
    assert len(ds.dask) == 3
    assert len(ds.divisions) == len(ds.dask) + 1
    assert isinstance(ds.divisions[0], type(s.index[0]))
    tm.assert_series_equal(s, ds.compute())


def test_from_pandas_non_sorted():
    df = pd.DataFrame({'x': [1, 2, 3]}, index=[3, 1, 2])
    ddf = dd.from_pandas(df, npartitions=2, sort=False)
    assert not ddf.known_divisions
    assert_eq(df, ddf)

    ddf = dd.from_pandas(df, chunksize=2, sort=False)
    assert not ddf.known_divisions
    assert_eq(df, ddf)


def test_from_pandas_single_row():
    df = pd.DataFrame({'x': [1]}, index=[1])
    ddf = dd.from_pandas(df, npartitions=1)
    assert ddf.divisions == (1, 1)
    assert_eq(ddf, df)


def test_from_pandas_with_datetime_index():
    df = pd.DataFrame({"Date": ["2015-08-28", "2015-08-27", "2015-08-26",
                                "2015-08-25", "2015-08-24", "2015-08-21",
                                "2015-08-20", "2015-08-19", "2015-08-18"],
                       "Val": list(range(9))})
    df.Date = df.Date.astype('datetime64')
    ddf = dd.from_pandas(df, 2)
    assert_eq(df, ddf)
    ddf = dd.from_pandas(df, chunksize=2)
    assert_eq(df, ddf)


def test_DataFrame_from_dask_array():
    x = da.ones((10, 3), chunks=(4, 2))

    df = dd.from_dask_array(x, ['a', 'b', 'c'])
    assert isinstance(df, dd.DataFrame)
    tm.assert_index_equal(df.columns, pd.Index(['a', 'b', 'c']))
    assert list(df.divisions) == [0, 4, 8, 9]
    assert (df.compute(get=get_sync).values == x.compute(get=get_sync)).all()

    # dd.from_array should re-route to from_dask_array
    df2 = dd.from_array(x, columns=['a', 'b', 'c'])
    assert isinstance(df, dd.DataFrame)
    tm.assert_index_equal(df2.columns, df.columns)
    assert df2.divisions == df.divisions


def test_Series_from_dask_array():
    x = da.ones(10, chunks=4)

    ser = dd.from_dask_array(x, 'a')
    assert isinstance(ser, dd.Series)
    assert ser.name == 'a'
    assert list(ser.divisions) == [0, 4, 8, 9]
    assert (ser.compute(get=get_sync).values == x.compute(get=get_sync)).all()

    ser = dd.from_dask_array(x)
    assert isinstance(ser, dd.Series)
    assert ser.name is None

    # dd.from_array should re-route to from_dask_array
    ser2 = dd.from_array(x)
    assert isinstance(ser2, dd.Series)
    assert_eq(ser, ser2)


def test_from_dask_array_compat_numpy_array():
    x = da.ones((3, 3, 3), chunks=2)

    with pytest.raises(ValueError):
        dd.from_dask_array(x)       # dask

    with pytest.raises(ValueError):
        dd.from_array(x.compute())  # numpy

    x = da.ones((10, 3), chunks=(3, 3))
    d1 = dd.from_dask_array(x)       # dask
    assert isinstance(d1, dd.DataFrame)
    assert (d1.compute().values == x.compute()).all()
    tm.assert_index_equal(d1.columns, pd.Index([0, 1, 2]))

    d2 = dd.from_array(x.compute())  # numpy
    assert isinstance(d1, dd.DataFrame)
    assert (d2.compute().values == x.compute()).all()
    tm.assert_index_equal(d2.columns, pd.Index([0, 1, 2]))

    with pytest.raises(ValueError):
        dd.from_dask_array(x, columns=['a'])       # dask

    with pytest.raises(ValueError):
        dd.from_array(x.compute(), columns=['a'])  # numpy

    d1 = dd.from_dask_array(x, columns=['a', 'b', 'c'])       # dask
    assert isinstance(d1, dd.DataFrame)
    assert (d1.compute().values == x.compute()).all()
    tm.assert_index_equal(d1.columns, pd.Index(['a', 'b', 'c']))

    d2 = dd.from_array(x.compute(), columns=['a', 'b', 'c'])  # numpy
    assert isinstance(d1, dd.DataFrame)
    assert (d2.compute().values == x.compute()).all()
    tm.assert_index_equal(d2.columns, pd.Index(['a', 'b', 'c']))


def test_from_dask_array_compat_numpy_array_1d():

    x = da.ones(10, chunks=3)
    d1 = dd.from_dask_array(x)       # dask
    assert isinstance(d1, dd.Series)
    assert (d1.compute().values == x.compute()).all()
    assert d1.name is None

    d2 = dd.from_array(x.compute())  # numpy
    assert isinstance(d1, dd.Series)
    assert (d2.compute().values == x.compute()).all()
    assert d2.name is None

    d1 = dd.from_dask_array(x, columns='name')       # dask
    assert isinstance(d1, dd.Series)
    assert (d1.compute().values == x.compute()).all()
    assert d1.name == 'name'

    d2 = dd.from_array(x.compute(), columns='name')  # numpy
    assert isinstance(d1, dd.Series)
    assert (d2.compute().values == x.compute()).all()
    assert d2.name == 'name'

    # passing list via columns results in DataFrame
    d1 = dd.from_dask_array(x, columns=['name'])       # dask
    assert isinstance(d1, dd.DataFrame)
    assert (d1.compute().values == x.compute()).all()
    tm.assert_index_equal(d1.columns, pd.Index(['name']))

    d2 = dd.from_array(x.compute(), columns=['name'])  # numpy
    assert isinstance(d1, dd.DataFrame)
    assert (d2.compute().values == x.compute()).all()
    tm.assert_index_equal(d2.columns, pd.Index(['name']))


def test_from_dask_array_struct_dtype():
    x = np.array([(1, 'a'), (2, 'b')], dtype=[('a', 'i4'), ('b', 'object')])
    y = da.from_array(x, chunks=(1,))
    df = dd.from_dask_array(y)
    tm.assert_index_equal(df.columns, pd.Index(['a', 'b']))
    assert_eq(df, pd.DataFrame(x))

    assert_eq(dd.from_dask_array(y, columns=['b', 'a']),
              pd.DataFrame(x, columns=['b', 'a']))


def test_to_castra():
    castra = pytest.importorskip('castra')
    blosc = pytest.importorskip('blosc')
    if (LooseVersion(blosc.__version__) == '1.3.0' or
            LooseVersion(castra.__version__) < '0.1.8'):
        pytest.skip()
    df = pd.DataFrame({'x': ['a', 'b', 'c', 'd'],
                       'y': [2, 3, 4, 5]},
                      index=pd.Index([1., 2., 3., 4.], name='ind'))
    a = dd.from_pandas(df, 2)

    c = a.to_castra()
    b = c.to_dask()
    try:
        tm.assert_frame_equal(df, c[:])
        tm.assert_frame_equal(b.compute(), df)
    finally:
        c.drop()

    c = a.to_castra(categories=['x'])
    try:
        assert c[:].dtypes['x'] == 'category'
    finally:
        c.drop()

    c = a.to_castra(sorted_index_column='y')
    try:
        tm.assert_frame_equal(c[:], df.set_index('y'))
    finally:
        c.drop()

    delayed = a.to_castra(compute=False)
    assert isinstance(delayed, Delayed)
    c = delayed.compute()
    try:
        tm.assert_frame_equal(c[:], df)
    finally:
        c.drop()

    # make sure compute=False preserves the same interface
    c1 = a.to_castra(compute=True)
    c2 = a.to_castra(compute=False).compute()
    try:
        tm.assert_frame_equal(c1[:], c2[:])
    finally:
        c1.drop()
        c2.drop()


def test_from_castra():
    castra = pytest.importorskip('castra')
    blosc = pytest.importorskip('blosc')
    if (LooseVersion(blosc.__version__) == '1.3.0' or
            LooseVersion(castra.__version__) < '0.1.8'):
        pytest.skip()
    df = pd.DataFrame({'x': ['a', 'b', 'c', 'd'],
                       'y': [2, 3, 4, 5]},
                      index=pd.Index([1., 2., 3., 4.], name='ind'))
    a = dd.from_pandas(df, 2)

    c = a.to_castra()
    with_castra = dd.from_castra(c)
    with_fn = dd.from_castra(c.path)
    with_columns = dd.from_castra(c, 'x')
    try:
        tm.assert_frame_equal(df, with_castra.compute())
        tm.assert_frame_equal(df, with_fn.compute())
        tm.assert_series_equal(df.x, with_columns.compute())
    finally:
        # Calling c.drop() is a race condition on drop from `with_fn.__del__`
        # and c.drop. Manually `del`ing gets around this.
        del with_fn, c


def test_from_castra_with_selection():
    """ Optimizations fuse getitems with load_partitions

    We used to use getitem for both column access and selections
    """
    castra = pytest.importorskip('castra')
    blosc = pytest.importorskip('blosc')
    if (LooseVersion(blosc.__version__) == '1.3.0' or
            LooseVersion(castra.__version__) < '0.1.8'):
        pytest.skip()
    df = pd.DataFrame({'x': ['a', 'b', 'c', 'd'],
                       'y': [2, 3, 4, 5]},
                      index=pd.Index([1., 2., 3., 4.], name='ind'))
    a = dd.from_pandas(df, 2)

    b = dd.from_castra(a.to_castra())

    assert_eq(b[b.y > 3].x, df[df.y > 3].x)


def test_to_bag():
    pytest.importorskip('dask.bag')
    a = pd.DataFrame({'x': ['a', 'b', 'c', 'd'],
                      'y': [2, 3, 4, 5]},
                     index=pd.Index([1., 2., 3., 4.], name='ind'))
    ddf = dd.from_pandas(a, 2)

    assert ddf.to_bag().compute() == list(a.itertuples(False))
    assert ddf.to_bag(True).compute() == list(a.itertuples(True))
    assert ddf.x.to_bag(True).compute() == list(a.x.iteritems())
    assert ddf.x.to_bag().compute() == list(a.x)
