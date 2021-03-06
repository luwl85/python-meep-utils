#!/usr/bin/env python
#coding:utf8
"""
This module contains several implementations of the AbstractMEEPModel class. Each of these classes
defines some structure made of dielectrics or metal, along with its dimensions, frequency of the source,
and many parameters. 

One of the classes is loaded by the `scatter.py' file, which is supposed to compute the effective 
parameters of a metamaterial. Therefore, all structures defined
by this module are assumed to be a single unit cell of a 3-D periodic lattice of the metamaterial.

In general, a wave is sent along the z-axis, its electric field being oriented along the x-axis and its 
magnetic field along the y-axis. The transmitted and reflected fields are recorded in each time step, and 
processed afterwards using the Fourier transform and the s-parameter method to retrieve the effective 
index of refraction of the metamaterial. etc.

Some of the parameters that can be passed to the structure are shared among most of them. Their meaning follows:
    * comment     -- any user-defined string (which may however also help defining the structure)
    * simtime     -- full simulation time, higher value leads to better spectral resolution
    * resolution  -- the size of one voxel in the FDTD grid; halving the value improves accuracy, but needs 16x CPU time
    * cellsize    -- the x- and y-dimensions of the simulation
    * padding     -- the z-distance between the monitors and the unit cell; higher values reduce evanescent field artifacts
    * Kx, Ky      -- the reflection and transmission can be also computed for oblique incidence, 
                     which can be defined by forcing nonzero perpendicular components of the K-vector
    * cellnumber  -- for well-behaved structures the eff-param retrieval should give same results for multiple cells stacked
Remaining parameters are specific for the given structure, and could be hopefully readable in its definition.
Note that `scatter.py' also accepts extra parameters, described in its header, that are not passed to the model.
"""
import time, sys, os
import numpy as np
from scipy.constants import c, epsilon_0, mu_0

import meep_utils, meep_materials
from meep_utils import in_sphere, in_xcyl, in_ycyl, in_zcyl, in_xslab, in_yslab, in_zslab, in_ellipsoid
import meep_mpi as meep
#import meep

class SphereWire(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=30e-12, resolution=4e-6, cellsize=100e-6, cellnumber=1, padding=50e-6, 
            radius=30e-6, wirethick=0, wirecut=0, loss=1, epsilon="TiO2", **other_args):
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "SphereWire"    
        self.src_freq, self.src_width = 1000e9, 4000e9    # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (10e9, 3000e9)    # Which frequencies will be saved to disk
        self.pml_thickness = .1*c/self.src_freq

        self.size_x = cellsize if (radius>0 or wirecut>0) else resolution/1.8
        self.size_y = cellsize
        self.size_z = cellnumber*cellsize + 4*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(cellsize*cellnumber/2)-padding, (cellsize*cellnumber/2)+padding)
        self.cellcenters = np.arange((1-cellnumber)*cellsize/2, cellnumber*cellsize/2, cellsize)

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Define materials (with manual Lorentzian clipping) 
        self.materials = []  
        if radius > 0:
            if epsilon=="TiO2":     ## use titanium dioxide if permittivity not specified...
                tio2 = meep_materials.material_TiO2(where=self.where_sphere) 
                if loss != 1: tio2.pol[0]['gamma'] *= loss   ## optionally modify the first TiO2 optical phonon to have lower damping
            else:           ## ...or define a custom dielectric if permittivity not specified
                tio2 = meep_materials.material_dielectric(where=self.where_sphere, eps=float(self.epsilon)) 
            self.fix_material_stability(tio2, verbose=0) ##f_c=2e13,  rm all osc above the first one, to optimize for speed 
            self.materials.append(tio2)

        if wirethick > 0:
            au = meep_materials.material_Au(where=self.where_wire)
            #au.pol[0]['sigma'] /= 100
            #au.pol[0]['gamma'] *= 10000
            self.fix_material_stability(au, verbose=0)
            self.materials.append(au)

        ## Test the validity of the model
        meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        self.test_materials()

    def where_sphere(self, r):
        for cellc in self.cellcenters:
            if  in_sphere(r, cx=self.resolution/4, cy=self.resolution/4, cz=cellc+self.resolution/4, rad=self.radius):
                return self.return_value             # (do not change this line)
        return 0
    def where_wire(self, r):
        for cellc in self.cellcenters:
            if in_xslab(r, cx=self.resolution/4, d=self.wirecut):
                return 0
            if  in_xcyl(r, cy=self.size_y/2+self.resolution/4, cz=cellc, rad=self.wirethick) or \
                    in_xcyl(r, cy= -self.size_y/2+self.resolution/4, cz=cellc, rad=self.wirethick):
                return self.return_value             # (do not change this line)
        return 0
#}}}
class RodArray(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=100e-12, resolution=4e-6, cellsize=100e-6, cellnumber=1, padding=20e-6, 
            radius=10e-6, eps2=100, **other_args):

        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation
        self.simulation_name = "RodArray"

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Constants for the simulation
        self.simtime = simtime      # [s]
        self.src_freq, self.src_width = 2000e9, 4000e9     # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (0e9, 2000e9)     # Which frequencies will be saved to disk
        self.pml_thickness = .1*c/self.src_freq

        self.size_x, self.size_y  = self.resolution*2, cellsize
        self.size_z = cellnumber*cellsize + 4*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(cellsize*cellnumber/2)-padding, (cellsize*cellnumber/2)+padding)
        self.cellcenters = np.arange((1-cellnumber)*cellsize/2, cellnumber*cellsize/2, cellsize)

        ## Define materials
        self.materials = [meep_materials.material_TiO2(where = self.where_TiO2)]  
        #self.materials = [meep_materials.material_dielectric(where = self.where_TiO2, eps=eps2)]  

        for m in self.materials: self.fix_material_stability(m)
        self.test_materials()

    def where_TiO2(self, r):
        #if  in_sphere(r, cx=0, cy=0, cz=0, rad=self.radius) and not  in_sphere(r, cx=0, cy=0, cz=0, rad=self.radius*.75):
        if  in_xcyl(r, cy=0, cz=0, rad=self.radius):
            return self.return_value             # (do not change this line)
        return 0
#}}}
class Slab(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=100e-12, resolution=2e-6, cellnumber=1, cellsize=100e-6, padding=50e-6, 
            fillfraction=0.5, epsilon=2, **other_args):
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "Slab"    
        self.src_freq, self.src_width = 1000e9, 4000e9  # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (10e9, 2000e9)    # Which frequencies will be saved to disk
        self.pml_thickness = 0.1*c/self.src_freq

        self.size_x = resolution*2 
        self.size_y = resolution
        self.size_z = cellnumber*cellsize + 4*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(cellsize*cellnumber/2)-padding, (cellsize*cellnumber/2)+padding)
        self.cellcenters = np.arange((1-cellnumber)*cellsize/2, cellnumber*cellsize/2, cellsize)

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Define materials
        # note: for optical range, it was good to supply f_c=5e15 to fix_material_stability
        if 'Au' in comment:           
            m = meep_materials.material_Au(where=self.where_slab)
            self.fix_material_stability(m, verbose=0) ## rm all osc above the first one, to optimize for speed 
        elif 'Ag' in comment:           
            m = meep_materials.material_Ag(where=self.where_slab)
            self.fix_material_stability(m, verbose=0) ## rm all osc above the first one, to optimize for speed 
        else:
            m = meep_materials.material_dielectric(where=self.where_slab, loss=0.001, eps=epsilon)
        self.materials = [m]

        ## Test the validity of the model
        #meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                #draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        #self.test_materials()

    def where_slab(self, r):
        for cellc in self.cellcenters:
            if in_zslab(r, d=self.cellsize*self.fillfraction, cz=cellc):
                return self.return_value             # (do not change this line)
        return 0
#}}}
class ESRRArray(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=50e-12, resolution=4e-6, cellsize=100e-6, cellnumber=1, padding=20e-6, 
            radius=40e-6, wirethick=6e-6, srrthick=6e-6, splitting=26e-6, splitting2=0e-6, capacitorr=10e-6, 
            cbarthick=0e-6, insplitting=100e-6, incapacitorr=0e-6, **other_args):
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "SRRArray"    
        self.src_freq, self.src_width = 1000e9, 4000e9    # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (10e9, 2000e9)    # Which frequencies will be saved to disk
        self.pml_thickness = 20e-6

        self.size_x = cellsize 
        self.size_y = cellsize
        self.size_z = cellnumber*cellsize + 4*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(cellsize*cellnumber/2)-padding, (cellsize*cellnumber/2)+padding)
        self.cellcenters = np.arange((1-cellnumber)*cellsize/2, cellnumber*cellsize/2, cellsize)

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Define materials
        self.materials = []  

        au = meep_materials.material_Au(where=self.where_wire)
        self.fix_material_stability(au, verbose=0)
        self.materials.append(au)

        ## Test the validity of the model
        meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        self.test_materials()

    def where_wire(self, r):
        dd=self.resolution/4
        for cellc in self.cellcenters:
            ## define the wires
            if  in_xcyl(r, cy=self.size_y/2, cz=cellc, rad=self.wirethick) or \
                    in_xcyl(r, cy= -self.size_y/2, cz=cellc, rad=self.wirethick):
                        return self.return_value             # (do not change this line)

            if (    # define the first splitting of SRR
                    not (r.z()>cellc+self.radius/2 and in_xslab(r, cx=dd, d=self.splitting))  
                    # define the 2nd splitting for symmetric SRR
                    and not (r.z()<cellc-self.radius/2 and in_xslab(r, cx=dd, d=self.splitting2))):
                # make the ring (without the central bar)
                if (in_ycyl(r, cx=dd, cz=cellc, rad=self.radius+self.srrthick/2)          # outer radius
                        and in_yslab(r, cy=dd, d=self.srrthick)                             # delimit to a disc
                        and not in_ycyl(r, cx=dd, cz=cellc, rad=self.radius-self.srrthick/2)):    # subtract inner radius 
                    return self.return_value             # (do not change this line)
                # optional capacitor pads
                if (self.splitting > 0
                        and in_xcyl(r, cy=dd, cz=cellc+self.radius, rad=self.capacitorr) 
                        and in_xslab(r, cx=dd, d=self.splitting+2*self.srrthick)):          
                    return self.return_value             # (do not change this line)
                # optional capacitor pads on second splitting
                if (self.splitting2 > 0 
                        and in_xcyl(r, cy=dd, cz=cellc-self.radius, rad=self.capacitorr) 
                        and in_xslab(r, cx=dd, d=self.splitting2+2*self.srrthick)):          
                    return self.return_value             # (do not change this line)

            if (self.cbarthick > 0 
                    # def splitting in the central bar for ESRR (the bar is completely disabled if insplitting high enough)
                    and not (in_zslab(r,cz=cellc,d=self.radius) and in_xslab(r, cx=dd, d=self.insplitting))):
                if (in_ycyl(r, cx=dd, cz=cellc, rad=self.radius+self.srrthick/2)         # outer radius
                        and in_yslab(r, cy=dd, d=self.srrthick)                          # delimit to a disc
                        and in_zslab(r,cz=cellc,d=self.cbarthick)):                       # but allow the central bar
                    return self.return_value             # (do not change this line)

                if ((self.insplitting > 0)
                        and in_xcyl(r, cy=dd, cz=cellc, rad=self.incapacitorr) 
                        and in_xslab(r, cx=dd, d=self.insplitting+2*self.srrthick)):          # optional capacitor pads
                    return self.return_value             # (do not change this line)

        return 0
#}}}
class SphereInDiel(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=30e-12, resolution=4e-6, cellsize=100e-6, cellnumber=1, padding=50e-6, 
            radius=30e-6, wirethick=0, wirecut=0, loss=1, epsilon="TiO2", diel=1, **other_args):
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "SphereWire"    
        self.src_freq, self.src_width = 1000e9, 4000e9    # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (10e9, 3000e9)    # Which frequencies will be saved to disk
        self.pml_thickness = .1*c/self.src_freq

        self.size_x = cellsize if (radius>0 or wirecut>0) else resolution/1.8
        self.size_y = cellsize
        self.size_z = cellnumber*cellsize + 4*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(cellsize*cellnumber/2)-padding, (cellsize*cellnumber/2)+padding)
        self.cellcenters = np.arange((1-cellnumber)*cellsize/2, cellnumber*cellsize/2, cellsize)

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Define materials (with manual Lorentzian clipping) 
        self.materials = []  
        if radius > 0:
            if epsilon=="TiO2":     ## use titanium dioxide if permittivity not specified...
                tio2 = meep_materials.material_TiO2(where=self.where_sphere) 
                if loss != 1: tio2.pol[0]['gamma'] *= loss   ## optionally modify the first TiO2 optical phonon to have lower damping
                else:           ## ...or define a custom dielectric if permittivity not specified
                    tio2 = meep_materials.material_dielectric(where=self.where_sphere, eps=float(self.epsilon)) 
            self.fix_material_stability(tio2, verbose=0) ##f_c=2e13,  rm all osc above the first one, to optimize for speed 
            self.materials.append(tio2)

        self.materials.append(meep_materials.material_dielectric(where=self.where_diel, eps=self.diel))

        if wirethick > 0:
            au = meep_materials.material_Au(where=self.where_wire)
            #au.pol[0]['sigma'] /= 100
            #au.pol[0]['gamma'] *= 10000
            self.fix_material_stability(au, verbose=0)
            self.materials.append(au)

        ## Test the validity of the model
        meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        self.test_materials()

    def where_sphere(self, r):
        for cellc in self.cellcenters:
            if  in_sphere(r, cx=self.resolution/4, cy=self.resolution/4, cz=cellc+self.resolution/4, rad=self.radius):
                return self.return_value             # (do not change this line)
        return 0
    def where_diel(self, r):
        for cellc in self.cellcenters:
            if in_sphere(r, cx=self.resolution/4, cy=self.resolution/4, cz=cellc+self.resolution/4, rad=self.radius):
                return 0
        for cellc in self.cellcenters:
            if in_zslab(r, cz=0, d=self.cellsize):
                return self.return_value             # (do not change this line)
        return 0
    def where_wire(self, r):
        for cellc in self.cellcenters:
            if in_xslab(r, cx=self.resolution/4, d=self.wirecut):
                return 0
            if  in_xcyl(r, cy=self.size_y/2+self.resolution/4, cz=cellc, rad=self.wirethick) or \
                    in_xcyl(r, cy= -self.size_y/2+self.resolution/4, cz=cellc, rad=self.wirethick):
                        return self.return_value             # (do not change this line)
        return 0
#}}}
class Fishnet(meep_utils.AbstractMeepModel): #{{{       single-layer fishnet
    def __init__(self, comment="", simtime=150e-12, resolution=4e-6, cellsize=100e-6, cellnumber=1, padding=100e-6, 
            cornerradius=30e-6, xholesize=80e-6, yholesize=80e-6, slabthick=12e-6, slabcdist=0, **other_args):
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "Fishnet"    
        self.src_freq, self.src_width = 1000e9, 4000e9    # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (10e9, 4000e9)    # Which frequencies will be saved to disk
        self.pml_thickness = .1*c/self.src_freq

        self.size_x = cellsize
        if yholesize == "inf" or yholesize == np.inf:
            self.size_y = resolution/1.8
            yholesize = np.inf
        else: 
            self.size_y = cellsize
        self.size_z = cellnumber*cellsize + 4*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(cellsize*cellnumber/2)-padding, (cellsize*cellnumber/2)+padding)
        self.cellcenters = np.arange((1-cellnumber)*cellsize/2, cellnumber*cellsize/2, cellsize)

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Define materials (with manual Lorentzian clipping) 
        au = meep_materials.material_Au(where=self.where_fishnet)
        au.pol[0]['sigma'] /= 10      # adjust losses
        au.pol[0]['gamma'] *= 10
        self.fix_material_stability(au, verbose=0)
        self.materials = [au]  

        ## Test the validity of the model
        meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        self.test_materials()

    def where_fishnet(self, r):
        dd=self.resolution/4
        xhr, yhr = self.xholesize/2-self.cornerradius, self.yholesize/2-self.cornerradius
        for cellc in self.cellcenters:
            if (in_zslab(r, cz=-self.slabcdist/2, d=self.slabthick) or in_zslab(r, cz=+self.slabcdist/2, d=self.slabthick)):
                if not (in_xslab(r, cx=dd, d=2*xhr) and \
                        in_yslab(r, cy=dd, d=self.yholesize)) and \
                        not (in_xslab(r, cx=dd, d=self.xholesize) and \
                        in_yslab(r, cy=dd, d=2*yhr)) and \
                        not in_zcyl(r, cx=dd+xhr, cy=dd+yhr, rad=self.cornerradius) and \
                        not in_zcyl(r, cx=dd-xhr, cy=dd+yhr, rad=self.cornerradius) and \
                        not in_zcyl(r, cx=dd+xhr, cy=dd-yhr, rad=self.cornerradius) and \
                        not in_zcyl(r, cx=dd-xhr, cy=dd-yhr, rad=self.cornerradius):
                            return self.return_value             # (do not change this line)
        return 0
#}}}
class TMathieu_Grating(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=200e-15, resolution=20e-9, cellnumber=1, padding=50e-6, 
            tdist=50e-6, ldist=100e-6, rcore1=6e-6, rclad1=0, rcore2=6e-6, tshift=0, **other_args):
        """ I have a red laser (spot size : 2mm of diameter) that goes through 2 grids placed a 50cm (see pictures below) but 100um apart from each other. A photomultiplier is placed behind the grids at 1m. During the experiment the second grid moves transversally and alternatively block the light and let the light reaching the photomultiplier. The grids induce a diffraction pattern, of which we only collect the central bright spot with the photomultiplier (a pinhole is placed in front of it with a 2mm diameter hole). What I would like to do is to simulate the profile of intensity of the light collected at the photomultiplier while the second grid moves. That's a first thing. Secondly, I would like to simulate how the profile changes while some material is deposit on the bars of the first grids and obstruct slowly the light to go through. So what matters to me is to recorded "how much light" of the initial light reach my PM while the second grid moves for various thicknesses of material deposited on the first one. """
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "TMathieu_Grating"    
        self.src_freq, self.src_width = 500e12, 2000e12    # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (380e12, 730e12)    # Which frequencies will be saved to disk
        self.pml_thickness = 500e-9

        self.size_x = resolution*1.8 
        self.size_y = tdist
        self.size_z = ldist + 2*padding + 2*self.pml_thickness
        self.monitor_z1, self.monitor_z2 = (-(ldist/2)-padding, (ldist/2)+padding)
        cellsize = ldist+2*padding

        self.register_locals(locals(), other_args)          ## Remember the parameters

        ## Define materials (with manual Lorentzian clipping) 
        self.materials = []  

        au = meep_materials.material_Au(where=self.where_wire)
        self.fix_material_stability(au, verbose=0)
        self.materials.append(au)

        ## Test the validity of the model
        meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        self.test_materials()

    def where_wire(self, r):
        if  in_xcyl(r, cy=0, cz=-self.ldist/2, rad=self.rcore1):                        ## first grid
            return self.return_value             # (do not change this line)

        if  in_xcyl(r, cy=self.tshift, cz=self.ldist/2, rad=self.rcore2) or \
                in_xcyl(r, cy=self.tshift-self.size_y, cz=self.ldist/2, rad=self.rcore2):       ## second grid may be transversally shifted
            return self.return_value             # (do not change this line)

        return 0
#}}}
class HalfSpace(meep_utils.AbstractMeepModel): #{{{
    def __init__(self, comment="", simtime=100e-15, resolution=10e-9, cellnumber=1, padding=200e-9, cellsize = 200e-9,
            epsilon=33.97, blend=0, **other_args):
        """ This structure demonstrates that scatter.py can also be used for samples on a substrate with an infinite 
        thickness. The back side of the substrate is not simulated, and it is assumed there will be no Fabry-Perot
        interferences between its sides.

        The monitor planes are enabled to be placed also inside a dielectric. In which case the wave amplitude is 
        adjusted so that the light intensity is maintained. The field amplitudes and phases have physical meaning 
        only when both monitor planes are in the same medium, though.

        Besides, the example demonstrates that on a steep interface with air the transmitted and reflected waves have 
        exactly the same energy with the choice of permittivity: ((1+.5**.5)/(1-.5**.5))**2, that is roughly 33.97.
        
        """
        meep_utils.AbstractMeepModel.__init__(self)        ## Base class initialisation

        ## Constant parameters for the simulation
        self.simulation_name = "HalfSpace"    
        self.src_freq, self.src_width = 500e12, 100e12    # [Hz] (note: gaussian source ends at t=10/src_width)
        self.interesting_frequencies = (10e12, 1000e12)    # Which frequencies will be saved to disk
        self.pml_thickness = 500e-9

        self.size_x = resolution*1.8 
        self.size_y = resolution*1.8
        self.size_z = blend + 2*padding + 2*self.pml_thickness + 6*resolution
        self.monitor_z1, self.monitor_z2 = (-padding, padding)
        self.register_locals(locals(), other_args)          ## Remember the parameters
        self.mon2eps = epsilon                  ## store what dielectric is the second monitor embedded in

        ## Define materials
        self.materials = []  
        if 'Au' in comment:         self.materials += [meep_materials.material_Au(where=self.where_m)]
        elif 'Ag' in comment:       self.materials += [meep_materials.material_Ag(where=self.where_m)]
        elif 'metal' in comment:    
            self.materials += [meep_materials.material_Au(where=self.where_m)]
            self.materials[-1].pol[1:] = []
            self.materials[-1].pol[0]['gamma'] = 0
        else:                       self.materials += [meep_materials.material_dielectric(where=self.where_m, eps=self.epsilon)]

        for m in self.materials: 
            self.fix_material_stability(m, f_c=3e15) ## rm all osc above the first one, to optimize for speed 

        ## Test the validity of the model
        meep_utils.plot_eps(self.materials, plot_conductivity=True, 
                draw_instability_area=(self.f_c(), 3*meep.use_Courant()**2), mark_freq={self.f_c():'$f_c$'})
        self.test_materials()

    def where_m(self, r):
        ## Just half-space
        #if r.z() > 0: return self.return_value

        ## Smooth sine-like transition from air to dielectric: a broadband anti-reflex layer
        if r.z()<-self.blend*.5: return 0
        if r.z()> self.blend*.5 or self.blend==0: return self.return_value
        return self.return_value*(1.+np.sin(r.z()/0.5/self.blend*np.pi/2))/2

        ## Single antireflex layer on substrate
        #if r.z() < 0 and r.z() > -self.padding/2:
            #return self.return_value**.5
        #if r.z() > 0:
            #return self.return_value
        return 0
#}}}

models = {'default':Slab, 'Slab':Slab, 'SphereWire':SphereWire, 'RodArray':RodArray, 'SRRArray':ESRRArray, 'ESRRArray':ESRRArray, 'SphereInDiel':SphereInDiel, 'Fishnet':Fishnet,  'TMathieu_Grating':TMathieu_Grating, 'HalfSpace':HalfSpace}

