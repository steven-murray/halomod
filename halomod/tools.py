'''
Created on Sep 9, 2013

@author: Steven
'''
import numpy as np
import scipy.integrate as intg
from scipy.stats import poisson
from fort.twohalo import twohalo_calc as thalo
import time

def power_to_corr_ogata(power, k, R, N=640, h=0.005):
    if not np.iterable(R):
        R = np.array([R])

    return thalo.power_to_corr(R, power, np.log(k.value), N, h)

def power_to_corr(power_func, R):
    """
    Calculate the correlation function given a power spectrum

    Parameters
    ----------
    power_func : callable
        A callable function which returns the natural log of power given lnk

    R : array_like
        The values of separation/scale to calculate the correlation at.

    """
    if not np.iterable(R):
        R = [R]

    corr = np.zeros_like(R)

    # the number of steps to fit into a half-period at high-k. 6 is better than 1e-4.
    minsteps = 8

    # set min_k, 1e-6 should be good enough
    mink = 1e-6

    temp_min_k = 1.0

    for i, r in enumerate(R):
        # getting maxk here is the important part. It must be a half multiple of
        # pi/r to be at a "zero", it must be >1 AND it must have a number of half
        # cycles > 38 (for 1E-5 precision).

        min_k = (2 * np.ceil((temp_min_k * r / np.pi - 1) / 2) + 0.5) * np.pi / r
        maxk = max(501.5 * np.pi / r, min_k)


        # Now we calculate the requisite number of steps to have a good dk at hi-k.
        nk = np.ceil(np.log(maxk / mink) / np.log(maxk / (maxk - np.pi / (minsteps * r))))

        lnk, dlnk = np.linspace(np.log(mink), np.log(maxk), nk, retstep=True)
        P = power_func(lnk)
        integ = P * np.exp(lnk) ** 2 * np.sin(np.exp(lnk) * r) / r

        corr[i] = (0.5 / np.pi ** 2) * intg.simps(integ, dx=dlnk)

    return corr


def overlapping_halo_prob(r, rv1, rv2):
    """
    The probability of non-overlapping ellipsoidal haloes (Tinker 2005 Appendix B)
    """
    if np.isscalar(rv1) and np.isscalar(rv2):
        x = r / (rv1 + rv2)
    else:
        x = r / np.add.outer(rv1, rv2)
    y = (x - 0.8) / 0.29

    if np.isscalar(y):
        if y <= 0:
            return 0
        elif y >= 1:
            return 1

    res = 3 * y ** 2 - 2 * y ** 3
    res[y <= 0] = 0.0
    res[y >= 1] = 1.0
    return res

def exclusion_window(k, r):
    """Top hat window function"""
    x = k * r
    return 3 * (np.sin(x) - x * np.cos(x)) / x ** 3

def dblsimps(X, dx, dy):
    """
    Perform double integration using simpsons rule
    """
    if len(X.shape) != 2:
        raise ValueError("dblsimps takes a matrix")
    if X.shape[0] % 2 != 1 or X.shape[1] != 1:
        # For now, knowing what's going in here, we just cut off the last value
        X = X[:-1, :-1]

    W = np.ones_like(X)

    W[range(1, len(W[:, 0]) - 1, 2), :] *= 4
    W[:, range(1, len(W[0, :]) - 1, 2)] *= 4
    W[range(2, len(W[:, 0]) - 1, 2), :] *= 2
    W[:, range(2, len(W[0, :]) - 1, 2)] *= 2

    return dx * dy * np.sum(W * X) / 9.0


def populate(centres, masses, profile,hodmod):
    """
    Populate a series of DM halos with galaxies given a HOD model.

    Parameters
    ----------
    centres : (N,3)-array
        The cartesian co-ordinates of the centres of the halos

    masses : array_like
        The masses (in M_sun/h) of the halos

    profile : type :class:`profile.Profile`
        A density profile to use.

    hodmod : object of type :class:`hod.HOD`
        A HOD model to use to populate the dark matter.

    Returns
    -------
    array :
        (N,3)-array of positions of galaxies.
    """

    cgal = np.zeros_like(masses)
    masses = np.array(masses)

    # Define which halos have central galaxies.
    cgal[np.random.rand() < hodmod.nc(masses)] = 1.0

    # Calculate the number of satellite galaxies in halos
    sgal = np.zeros_like(masses)
    sgal[cgal != 0.0] = poisson.rvs(hodmod.ns(masses[cgal != 0.0]))

    # Get an array ready, hopefully speeds things up a bit
    nhalos_with_gal = np.sum(cgal)
    allpos = np.empty((np.sum(sgal) + nhalos_with_gal, 3))

    # Assign central galaxy positions
    allpos[:nhalos_with_gal, :] = centres[cgal > 0]

    # Clean up some memory
    del cgal

    begin = nhalos_with_gal
    mask = sgal > 0
    sgal = sgal[mask]
    centres = centres[mask]
    M = masses[mask]

    # Now go through each halo and calculate galaxy positions
    start = time.time()
    for i, m in enumerate(M):
        end = begin + sgal[i]
        allpos[begin:end, :] = profile.populate(sgal[i], m, ba=1, ca=1) + centres[i, :]
        begin = end
    print "Took ", time.time() - start, " seconds, or ", (time.time() - start) / nhalos_with_gal, " each."
    print "MeanGal: ", np.mean(sgal + 1) , "MostGal: ", sgal.max() + 1
    return allpos
