
import numpy as np
import scipy.special as sp
import scipy.integrate as intg
from scipy.interpolate import UnivariateSpline as spline
import mpmath
import sys
from hmf import cosmo
import cosmolopy as cp

def get_profile(profile, delta_halo=200.0,
                cm_relation='zehavi', z=0.0, truncate=True,
                **cosmo_args):
    """
    A function that chooses the correct Profile class and returns it
    """
    if not truncate:
        profile = profile + "Inf"
    try:
        return getattr(sys.modules[__name__], profile)(delta_halo, cm_relation,
                                                       z, **cosmo_args)
    except AttributeError:
        raise AttributeError(str(profile) + "  is not a valid profile class")


class Profile(object):
    """
    Halo radial density profiles.
    
    This class provides basic building blocks for all kinds of fun with halo
    radial density profiles. It is modeled on the system described in 
    XXXX.XXXX (paper yet to be published). This means that subclasses providing
    specific profiles shapes, f(x) must provide very minimal other information
    for a range of products to be available.
    
    The "main" quantities available are the profile itself, its fourier pair, 
    and its convolution (this is not available for every profile). Furthermore,
    quantities such as the concentration-mass relation are provided, along with 
    tools such as those to generate a mock halo of the given profile. 

    Parameters
    ----------
    omegam : float, default 0.3
        Fractional matter density at current epoch
        
    delta_halo : float, default 200.0
        Overdensity of the halo definition, with respect to MEAN BACKGROUND density.
        
    cm_relation : str {'zehavi','duffy'}
        Identifies which concentration-mass relation to use
        
    z : float, default 0.0
        The redshift of the halo
    """
    def __init__(self, delta_halo=200.0, cm_relation='zehavi', z=0.0,
                 **cosmo_args):

        self._delta_halo = delta_halo
        if "default" not in cosmo_args:
            cosmo_args.update({"default":"planck1_base"})
        self._cosmo = cosmo.Cosmology(**cosmo_args)
        self._z = z
        self._cm_relation = cm_relation
        if hasattr(self, "_l"):
            self.has_lam = True
        else:
            self.has_lam = False

        self._mean_dens = 2.775e11 * cp.density.omega_M_z(z, **self._cosmo.cosmolopy_dict())

    # -- BASIC TRANSFORMATIONS --------------------------------------
    def _mvir_to_rvir(self, m):
        """ Return the virial radius corresponding to m"""
        return (3 * m / (4 * np.pi * self._delta_halo * self._mean_dens)) ** (1. / 3.)

    def _rvir_to_mvir(self, r):
        """Return the virial mass corresponding to r"""
        if self._delta_wrt == "mean":
            return 4 * np.pi * r ** 3 * self._delta_halo * self._mean_dens / 3
        else:
            return 4 * np.pi * r ** 3 * self._delta_halo * self._crit_dens / 3

    def _rs_from_m(self, m, c=None):
        """ 
        Return the scale radius for a halo of mass m
        
        Parameters
        ----------
        m : float
            mass of the halo
            
        c : float, default None
            concentration of the halo (if None, use cm_relation to get it).
        """
        if c is None:
            c = self.cm_relation(m)
        rvir = self._mvir_to_rvir(m)
        return rvir / c

    def _h(self, c=None, m=None):
        """ 
        The integral of f(x)*x^2 out to c 
        
        Parameters
        ----------
        c : float or array_like, optional
            The concentration(s) of the halo(s). Used ONLY if m is not specified.
            
        m : float or array_like, optional
            The mass of the halo. Determines the concentration if provided.
            
        .. note :: This function should be replaced with an analytic solution if 
                possible in derived classes.
        """
        if c is None and m is None:
            raise ValueError("Either c or m must be provided.")
        if m is not None:
            c = self.cm_relation(m)

        x, dx = np.linspace(1e-6, c, 2000, retstep=True)
        integrand = self._f(x) * x ** 2

        return intg.simps(integrand, dx=dx)

    def _p(self, K, c):
        """
        The reduced dimensionless fourier-transform of the profile
        
        This function should not need to be called by the user in general.
        
        Parameters
        ----------
        K : float or array_like
            The unit-less wavenumber k*r_s
        
        c : float or array_like
            The concentration
            
        .. note :: This should be replaced by an analytic function if possible
        """
        # Make sure we use enough steps to fit every period at least 5 times
        minsteps = 1000
        smallest_period = np.pi / K.max()
        dx = smallest_period / 5
        nsteps = int(np.ceil(c / dx))

        if nsteps < minsteps:
            nsteps = minsteps

        x, dx = np.linspace(0, c, nsteps, retstep=True)
        if len(K.shape) == 2:
            kk = np.linspace(np.log(K.min()), np.log(K.max()), 1000)
        else:
            kk = np.log(K)

        res = np.empty(len(kk))
        for i, k in enumerate(kk):
            integrand = x * self._f(x) * np.sin(np.exp(k) * x) / np.exp(k)
            res[i] = intg.simps(integrand, dx=dx)


        if len(K.shape) == 2:
                fit = spline(kk, res[i], k=3)
                res = fit(K)

        return res

    def _rho_s(self, c, r_s=None, norm=None):
        """ 
        The amplitude factor of the profile 
        
        Parameters
        ----------
        c : float or array of floats
            The concentration parameter
            
        norm : str or None, {None,"m","rho"}
            Normalisation for the amplitude. Can either be None (in which case
            the output is a density), "m" (in which case the output is inverse 
            volume) or "rho" in which case the output is dimensionless.
            
        r_s : float or array of floats
            The scale radius. This is only required if ``norm`` is "m".
        """
        if norm is None:
            rho = c ** 3 * self._delta_halo * self._mean_dens / (3 * self._h(c))
        elif norm is "m":
            rho = 1.0 / (4 * np.pi * r_s ** 3 * self._h(c))
        elif norm is "rho":
            rho = c ** 3 * self._delta_halo / (3 * self._h(c))

        return self._make_scalar(rho)

    def rho(self, r, m, norm=None, c=None, coord="r"):
        """
        The density at radius r of a halo of mass m.
        
        Parameters
        ----------
        r : float or array of floats
            The radial location(s). The units vary according to :attr:`coord`
            
        m : float or array of floats
            The mass(es) of the halo(s)
            
        norm : str, {``None``,``m``,``rho``}
            Normalisation of the density. 
            
        c : float or array of floats, default ``None``
            Concentration(s) of the halo(s). Must be same length as :attr:`m`.
            
        coord : str, {``r``,``x``,``s``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, r_s, x = self._get_r_variables(r, m, c, coord)
        rho = self._f(x) * self._rho_s(c, r_s, norm)
        rho[x > c] = 0.0

        return self._make_scalar(rho)

    def u(self, k, m, norm=None, c=None, coord="k"):
        """
        The fourier-transform of the density profile 
        
        Parameters
        ----------
        k : float or array of floats
            The radial wavenumber(s). The units vary according to :attr:`coord`
            
        m : float or array of floats
            The mass(es) of the halo(s)
            
        norm : str, {``None``,``m``,``rho``}
            Normalisation of the density. 
            
        c : float or array of floats, default ``None``
            Concentration(s) of the halo(s). Must be same length as :attr:`m`.
            
        coord : str, {``k``,``kappa``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, K = self._get_k_variables(k, m, c, coord)

        u = self._p(K, c) / self._h(c)

        if norm is None:
            u *= m
        elif norm != "m":
            raise ValueError(str(norm) + "is not a valid value for norm")

        return self._make_scalar(u)

    def lam(self, r, m, norm=None, c=None, coord='r'):
        """
        The density profile convolved with itself.
        
        Parameters
        ----------
        r : float or array of floats
            The radial location(s). The units vary according to :attr:`coord`
            
        m : float or array of floats
            The mass(es) of the halo(s)
            
        norm : str, {``None``,``m``,``rho``}
            Normalisation of the density. 
            
        c : float or array of floats, default ``None``
            Concentration(s) of the halo(s). Must be same length as :attr:`m`.
            
        coord : str, {``r``,``x``,``s``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, r_s, x = self._get_r_variables(r, m, c, coord)
        if self.has_lam:
            if norm in [None, "m"]:
                lam = self._l(x, c) * r_s ** 3 * self._rho_s(c, r_s, norm) ** 2
            else:
                raise ValueError("norm must be None or 'm'")
        else:
            raise AttributeError("this profile has no self-convolution defined.")
        return self._make_scalar(lam)

    def cdf(self, r, c=None, m=None, coord='r'):
        """
        The cumulative distribution function, :math:`m(<x)/m_v`
        
        Parameters
        ----------
        x : float or array_like
            The radial location -- units defined by :attr:`coord`
            
        c : float or array_like, optional
            The concentration. Only used if m not provided
            
        m : float or array_like, optional
            The mass of the halo. Defines the concentration if provided.
            
        coord : str, {``"x"``, ``"r"``, ``"s"``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, r_s, x = self._get_r_variables(r, m, c, coord)
        return self._h(x) / self._h(c)

    def populate(self, N, m, c=None, ba=1, ca=1, sort=False, norm=False):
        """
        Creates a mock halo with the current profile.
        """
        if c is None:
            c = self.cm_relation(m)

        # Internal max just buffers where the particles are created to before truncating
        internal_max = 1 / ca

        # Buffer the number of particles
        N_full = int(internal_max * N)

        # Interpolate the iCDF
        x = np.linspace(0, internal_max * c, 750)

        mass_enc = self.cdf(x, c, coord='x')

        icdf = spline(mass_enc, x, k=3)

        # Pick a random number
        rnd = np.random.random(N_full)

        # Calculate the radius x from the ICDF
        x = icdf(rnd)
        # Make sure we end up with N particles
        pos = np.zeros((N_full, 3))

        # Now assign the selected radii cartesian coordinates.
        # These will be uniformly distributed on the unit sphere.
        phi = 2 * np.pi * np.random.random(N_full)

        pos[:, 0] = x * (2 * np.random.random(N_full) - 1.0)

        rcynd = np.sqrt(x ** 2 - pos[:, 0] ** 2)
        pos[:, 1] = rcynd * np.cos(phi) * ba
        pos[:, 2] = rcynd * np.sin(phi) * ca

        # FIXME: the following lines should be there, but since spline isn't
        # perfect, they cause things that should be == c to be cut out.
        # pos = pos[x <= c, :]
        # x = x[x <= c]
        if len(x) >= N:
            x = x[:N]
            pos = pos[:N, :]
        else:
            while len(x) < N:
                rnd = np.random.random(N)
                x2 = icdf(rnd)

                pos2 = np.zeros((N, 3))

                # Now assign the selected radii cartesian coordinates.
                # These will be uniformly distributed on the unit sphere.
                phi = 2 * np.pi * np.random.random(N)

                pos2[:, 0] = x2 * (2 * np.random.random(N) - 1.0)

                rcynd = np.sqrt(x2 ** 2 - pos2[:, 0] ** 2)
                pos2[:, 1] = rcynd * np.cos(phi) * ba
                pos2[:, 2] = rcynd * np.sin(phi) * ca

                x2 = np.sqrt(pos2[:, 1] ** 2 + pos2[:, 2] ** 2 + pos2[:, 0] ** 2)

                pos2 = pos2[x <= c, :]
                x2 = x2[x <= c]
                if len(x2) > 0:
                    x = np.concatenate(x, x2)
                    pos = np.concatenate(pos, pos2)
                if len(x) > N:
                    x = x[:N]
                    pos = pos[:N, :]

        # Sort the particles in increasing r
        if sort:
            pos = pos[np.argsort(x), :]

        if not norm:
            pos *= self._rs_from_m(m, c)

        return pos



    def cm_relation(self, m):
        """
        The concentration-mass relation
        """
        if isinstance(self._cm_relation, str):
            return getattr(self, "_cm_" + self._cm_relation)(m)
        else:
            return self._cm_relation

    def _get_r_variables(self, r, m, c=None, coord="r"):
        if c is None:
            c = self.cm_relation(m)
        r_s = self._rs_from_m(m, c)

        if np.iterable(r) and np.iterable(r_s):
            if coord == "r":
                x = np.divide.outer(r, r_s)
            elif coord == "x":
                x = r
            elif coord == "s":
                x = np.outer(r, c)
        else:
            if coord == "r":
                x = r / r_s
            elif coord == "x":
                x = x
            elif coord == "s":
                x = r * c
        return np.atleast_1d(c, r_s, x)

    def _get_k_variables(self, k, m, c=None, coord="k"):

        if c is None:
            c = self.cm_relation(m)
        r_s = self._rs_from_m(m, c)

        if coord == "k":
            if np.iterable(k) and np.iterable(r_s):
                K = np.outer(k, r_s)
            else:
                K = k * r_s
        elif coord == "kappa":
            K = k

        return c, np.atleast_1d(K)

    def _make_scalar(self, x):
        if len(x) == 1:
            return x[0]
        else:
            return x

    #===========================================================================
    # CONCENTRATION-MASS RELATIONS
    #===========================================================================
    def _cm_duffy(self, m):
        return 6.71 * (m / (2.0 * 10 ** 12)) ** -0.091 * (1 + self._z) ** -0.44

    def _cm_zehavi(self, m):
        return ((m / 1.5e13) ** -0.13) * 9.0 / (1 + self._z)

    def _cm_bullock_rescaled(self, m):
        return (m / 10 ** 12.47) ** (-0.13) * 11 / (1 + self._z)

class ProfileInf(Profile):
    """
    An extended profile (not truncated at x=c)
    """
    def rho(self, r, m, norm=None, c=None, coord="r"):
        """
        The density at radius r of a halo of mass m.
        
        Parameters
        ----------
        r : float or array of floats
            The radial location(s). The units vary according to :attr:`coord`
            
        m : float or array of floats
            The mass(es) of the halo(s)
            
        norm : str, {``None``,``m``,``rho``}
            Normalisation of the density. 
            
        c : float or array of floats, default ``None``
            Concentration(s) of the halo(s). Must be same length as :attr:`m`.
            
        coord : str, {``r``,``x``,``s``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, r_s, x = self._get_r_variables(r, m, c, coord)

        rho = self._f(x) * self.rho_s(c, r_s, norm)

        return self._make_scalar(rho)

    def u(self, k, m, norm=None, c=None, coord="k"):
        """
        The fourier-transform of the density profile 
        
        Parameters
        ----------
        k : float or array of floats
            The radial wavenumber(s). The units vary according to :attr:`coord`
            
        m : float or array of floats
            The mass(es) of the halo(s)
            
        norm : str, {``None``,``m``,``rho``}
            Normalisation of the density. 
            
        c : float or array of floats, default ``None``
            Concentration(s) of the halo(s). Must be same length as :attr:`m`.
            
        coord : str, {``k``,``kappa``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, K = self._get_k_variables(k, m)

        u = self._p(K) / self._h(c)

        if norm is None:
            u *= m
        elif norm != "m":
            raise ValueError(str(norm) + "is not a valid value for norm")

        return self._make_scalar(u)

    def _p(self, K):
        """
        The dimensionless fourier-transform of the profile
        
        This should be replaced by an analytic function if possible
        """
        # Make sure we use enough steps to fit every period at least 5 times
        minsteps = 1000
        smallest_period = np.pi / K.max()
        dx = smallest_period / 5
        nsteps = int(np.ceil(c / dx))

        if nsteps < minsteps:
            nsteps = minsteps

        cc = 10.0
        tol = 1e-3
        allowed_diff = 0.8

        if len(K.shape) == 2:
            kk = np.linspace(np.log(K.min()), np.log(K.max()), 1000)
        else:
            kk = np.log(K)


        res = np.zeros(len(kk))
        for i, k in enumerate(kk):
            diff = 10.0
            j = 0
            while diff > tol and diff < allowed_diff:
                x, dx = np.linspace(j * cc, (j + 1) * cc, nsteps, retstep=True)

                integrand = x * self._f(x) * np.sin(np.exp(k) * x) / np.exp(k)
                this_iter = intg.simps(integrand, dx=dx)
                diff = abs((this_iter - res[i]) / this_iter)
                res[i] += this_iter
                j += 1
            if diff > allowed_diff:
                raise Exception("profile has no analytic transform and converges too slow numerically")

        if len(K.shape) == 2:
                fit = spline(kk, res[i], k=3)
                res = fit(K)

        return res

    def lam(self, r, m, norm=None, c=None, coord='r'):
        """
        The density profile convolved with itself.
        
        Parameters
        ----------
        r : float or array of floats
            The radial location(s). The units vary according to :attr:`coord`
            
        m : float or array of floats
            The mass(es) of the halo(s)
            
        norm : str, {``None``,``m``,``rho``}
            Normalisation of the density. 
            
        c : float or array of floats, default ``None``
            Concentration(s) of the halo(s). Must be same length as :attr:`m`.
            
        coord : str, {``r``,``x``,``s``}
            What the radial coordinate represents. ``r`` represents physical
            co-ordinates [units Mpc/h]. ``x`` is in units of the scale radius 
            (r_vir = c), and ``s`` is in units of the virial radius (r_vir = 1).
        """
        c, r_s, x = self._get_r_variables(r, m, c, coord)
        if self.has_lam:
            if norm in [None, "m"]:
                lam = self._l(x) * r_s ** 3 * self._rho_s(c, r_s, norm) ** 2
            else:
                raise ValueError("norm must be None or 'm'")
        else:
            raise AttributeError("this profile has no self-convolution defined.")
        return self._make_scalar(lam)

class NFW(Profile):
    def _f(self, x):
        return 1.0 / (x * (1 + x) ** 2)

    def _h(self, c):
        return np.log(1.0 + c) - c / (1.0 + c)

    def _p(self, K, c=None):
        bs, bc = sp.sici(K)
        asi, ac = sp.sici((1 + c) * K)
        return (np.sin(K) * (asi - bs) - np.sin(c * K) / ((1 + c) * K) + np.cos(K) * (ac - bc))


    def _l(self, x, c):
        result = np.zeros_like(x)

        if np.all(x > 2 * c):
            return result  # Stays as zero

        if len(x.shape) == 2:
            c = np.repeat(c, x.shape[0]).reshape(x.shape[0], x.shape[1])
        if len(x.shape) == 1:
            try:
                c = np.repeat(c[0], x.shape[0])
            except:
                c = np.repeat(c, x.shape[0])
        # GET LOW VALUES
        if np.any(x <= c):
            mask = x <= c
            x_lo = x[mask]
            c_lo = c[mask]
            a_lo = 1.0 / c_lo

            f2_lo = -4 * (1 + a_lo) + 2 * a_lo * x_lo * (1 + 2 * a_lo) + (a_lo * x_lo) ** 2
            f2_lo /= 2 * (x_lo * (1 + a_lo)) ** 2 * (2 + x_lo)
            f3_lo = np.log((1 + a_lo - a_lo * x_lo) * (1 + x_lo) / (1 + a_lo)) / x_lo ** 3
            f4 = np.log(1 + x_lo) / (x_lo * (2 + x_lo) ** 2)
            result[mask] = 4 * np.pi * (f2_lo + f3_lo + f4)
        # And high values
        if np.any(np.logical_and(x < 2 * c, x > c)):
            mask = np.logical_and(x > c, x <= 2 * c)
            x_hi = x[mask]
            c_hi = c[mask]
            a_hi = 1.0 / c_hi

            f2_hi = np.log((1 + a_hi) / (a_hi + a_hi * x_hi - 1)) / (x_hi * (2 + x_hi) ** 2)
            f3_hi = (x_hi * a_hi ** 2 - 2 * a_hi) / (2 * x_hi * (1 + a_hi) ** 2 * (2 + x_hi))
            result[mask] = 4 * np.pi * (f2_hi + f3_hi)


        return result


class NFWInf(NFW, ProfileInf):
    def _p(self, K):
        bs, bc = sp.sici(K)
        return 0.5 * ((np.pi - 2 * bs) * np.sin(K) - 2 * np.cos(K) * bc)

    def _l(self, x):

        f1 = 8 * np.pi / (x ** 2 * (x + 2))
        f2 = ((x ** 2 + 2 * x + 2)(np.log(1 + x)) / (x * (x + 2))) - 1

        return f1 * f2


class Hernquist(Profile):
    def _f(self, x):
        return 1.0 / (x * (1 + x) ** 3)

    def _h(self, c):
        return c ** 2 / (2 * (1 + c) ** 2)

    def _p(self, K, c):

        sk, ck = sp.sici(K)
        skp, ckp = sp.sici(K + c * K)

        f1 = K * ck * np.sin(K) - K * np.cos(K) * sk - 1
        f2 = -((1 + c) * K * np.cos(c * K) + np.sin(c * K)) / (1 + c) ** 2
        f3 = K ** 2 * (ckp * np.sin(K) - np.cos(K) * skp)

        return (-K / 2 * f1 + 0.5 * (f2 + f3)) / K


class HernquistInf(Hernquist, ProfileInf):
    def _p(self, K):
        si, ci = sp.sici(K)

        return 0.25 * (2 - K * (2 * ci * np.sin(K) + np.cos(K) * (np.pi - 2 * si)))

    def _l(self, x):

        h1 = (24 + 60 * x + 56 * x ** 2 + 24 * x ** 3 + 6 * x ** 4 + x ** 5) / (1 + x)
        h2 = 12 * (1 + x) * (2 + 2 * x + x ** 2) * np.log(1 + x) / x

        return 4 * np.pi * 4 * (h1 - h2) / (x ** 4 * (2 + x) ** 4)


class Moore(Profile):
    def _f(self, x):
        return 1.0 / (x ** 1.5 * (1 + x ** 1.5))

    def _h(self, c):
        return 2.*np.log(1 + c ** 1.5) / 3

    def cm_relation(self, m, z):
        c, r_s = super(Moore, self).cm_relation(m, z)
        r_s *= c / (c / 1.7) ** 0.9
        c = (c / 1.7) ** 0.9

        return c, r_s

class MooreInf(Moore, ProfileInf):
    def _p(self, K):
        G = lambda k : mpmath.meijerg([[1. / 6., 5. / 12., 11. / 12.], []],
                       [[1. / 6., 1. / 6., 5. / 12., 0.5, 2. / 3., 5. / 6., 11. / 12.], [0, 1. / 3.]],
                       k ** 6 / 46656.0) / (4 * np.sqrt(3) * np.pi ** (5 / 2) * k)

        if len(K.shape) == 2:
            K1 = np.reshape(K, -1)
            K1.sort()
        else:
            K1 = K
        res = np.zeros(len(K[K < 10 ** 3.2]))
        for i, k in enumerate(K1[K1 < 10 ** 3.2]):
            res[i] = G(k)

        fit = spline(np.log(K1[K1 < 10 ** 3.2]), np.log(res), k=1)
        res = np.reshape(np.exp(fit(np.log(np.reshape(K, -1)))), (len(K[:, 0]), len(K[0, :])))

        return res

class Constant(Profile):
    def _f(self, x):
        return 1.0

    def _h(self, c):
        return c ** 3 / 3.0

    def _p(self, K, c):
        return (-c * K * np.cos(c * K) + np.sin(c * K)) / K ** 3

class GeneralNFWLike(Profile):
    def __init__(self, alpha, *args, **kwargs):
        super(GeneralNFWLike, self).__init__(*args, **kwargs)
        self.alpha = alpha

    def _f(self, x):
        return 1.0 / (x ** self.alpha * (1 + x) ** (3 - self.alpha))

    def _h(self, c):
        c = np.complex(c)
        f1 = -(-c) ** self.alpha * c ** self.alpha
        f2 = mpmath.betainc(-c, 3 - self.alpha, self.alpha - 2)
        return (f1 * f2).real

class GeneralNFWLikeInf(GeneralNFWLike, ProfileInf):
    def _p(self, K):
        G = lambda k : mpmath.meijerg([[(self.alpha - 2) / 2.0, (self.alpha - 1) / 2.0], []],
                       [[0, 0, 0.5], [-0.5]],
                       k ** 2 / 4) / (np.sqrt(np.pi) * sp.gamma(3 - self.alpha))

        if len(K.shape) == 2:
            K1 = np.reshape(K, -1)
            K1.sort()
        else:
            K1 = K
        res = np.zeros(len(K[K < 10 ** 3.2]))
        for i, k in enumerate(K1[K1 < 10 ** 3.2]):
            res[i] = G(k)

        fit = spline(np.log(K1[K1 < 10 ** 3.2]), np.log(res), k=1)
        res = np.reshape(np.exp(fit(np.log(np.reshape(K, -1)))), (len(K[:, 0]), len(K[0, :])))

        return res