#!/usr/bin/env python
#-*- coding: utf-8 -*-
""" current_driven_homogenisation.py - an example python-meep simulation of how metamaterial
parameters can be retrieved in a more reliable way when the MM unit cell is excited by a 
volume source with a given K-vector.
(c) 2014 Filip Dominec, see http://fzu.cz/~dominecf/meep/ for more information """
import time, sys, os
import numpy as np
from scipy.constants import c, epsilon_0, mu_0

import meep_utils, meep_materials, metamaterial_models
from meep_utils import in_sphere, in_xcyl, in_ycyl, in_zcyl, in_xslab, in_yslab, in_zslab, in_ellipsoid
import meep_mpi as meep
#import meep

class AmplitudeMonitorVolume():#{{{
    def __init__(self, comp=None, size_x=None, size_y=None, size_z=None, Kx=0, Ky=0, Kz=0):
        self.comp=comp
        self.size_x = size_x
        self.size_y = size_y
        self.size_z = size_z
        self.Kx = Kx
        self.Ky = Ky
        self.Kz = Kz

        self.t = []
        self.waveform = []

    def average_field(self, field):
        """ Average field component in whole simulation volume
        """
        xcount, ycount, zcount = (1, 5, 3)
        field_sum = 0 
        for x in [x0*self.size_x/xcount+(self.size_x/2/xcount)-self.size_x/2 for x0 in range(xcount)]:
            for y in [y0*self.size_y/ycount+(self.size_y/2/ycount)-self.size_y/2 for y0 in range(ycount)]:
                for z in [z0*self.size_z/zcount+(self.size_z/2/zcount)-self.size_z/2 for z0 in range(zcount)]:
                    field_sum += (field.get_field(self.comp, meep.vec(x, y, z)) / np.exp(-1j*(self.Kx*x + self.Ky*y + self.Kz*z)) )
        return field_sum/(xcount*ycount*zcount)
        return sum_/(xcount*ycount)
    
    def record(self, field=None):
        self.t.append(field.time()/c)
        self.waveform.append(self.average_field(field))

    def get_waveforms(self):
        """ Return the recorded waveform (in time domain) """
        if len(self.t) <= 1:
            t, result_wform = np.array(self.t), np.array(self.waveform)
        else:
            t = np.array(self.t[:-1])
            if meep.is_magnetic(self.comp) or meep.is_B(self.comp):
                result_wform = np.array(self.waveform[:-1])/2. + np.array(self.waveform[1:])/2.
            else: 
                result_wform = np.array(self.waveform[:-1])
        return t, result_wform 
#}}}



# Model selection
model_param = meep_utils.process_param(sys.argv[1:])
model = metamaterial_models.models[model_param.get('model', 'default')](**model_param)

## Note: in CDH, we do not need any PML, padding nor multiple cells; cellsize thus overrides the dimensions given in model
model.size_x, model.size_y, model.size_z = model.cellsize, model.cellsize, model.cellsize

## Initialize volume and structure according to the model
vol = meep.vol3d(model.size_x, model.size_y, model.size_z, 1./model.resolution)


vol.center_origin()
s = meep_utils.init_structure(model=model, volume=vol, pml_axes="None")
f = meep.fields(s)
# Define the Bloch-periodic boundaries (any transversal component of k-vector is allowed)
f.use_bloch(meep.X, getattr(model, 'Kx', 0) / (-2*np.pi))
f.use_bloch(meep.Y, getattr(model, 'Ky', 0) / (-2*np.pi))
f.use_bloch(meep.Z, getattr(model, 'Kz', 0) / (-2*np.pi))

# Add the field source (see meep_utils for an example of how an arbitrary source waveform is defined)
if not getattr(model, 'frequency_domain', None):           ## Select the source dependence on time
    src_time_type = meep_utils.band_src_time(model.src_freq/c, model.src_width/c, model.simtime*c/10)
    #src_time_type = meep.gaussian_src_time(model.src_freq/c, model.src_width/c)
else:
    src_time_type = meep.continuous_src_time(getattr(model, 'frequency', None)/c)
srcvolume = meep.volume(                    ## Source must fill the whole simulation volume
        meep.vec(-model.size_x/2, -model.size_y/2, -model.size_z/2),
        meep.vec( model.size_x/2,  model.size_y/2, model.size_z/2))

class AmplitudeFactor(meep.Callback): 
    def __init__(self, Kx=0, Ky=0, Kz=0): 
        meep.Callback.__init__(self)
        (self.Kx, self.Ky, self.Kz) = Kx, Ky, Kz
    def complex_vec(self, vec):   ## Note: the 'vec' coordinates are _relative_ to the source center
        ## Current-driven homogenisation source forces the K-vector in whole unit cell
        return np.exp(-1j*(self.Kx*vec.x() + self.Ky*vec.y() + self.Kz*vec.z())) 
af = AmplitudeFactor(Kx=getattr(model, 'Kx',.0), Ky=getattr(model, 'Ky',.0), Kz=getattr(model, 'Kz',.0))
meep.set_AMPL_Callback(af.__disown__())
f.add_volume_source(meep.Ex, src_time_type, srcvolume, meep.AMPL)

## Define the volume monitor for CDH
monitor_options = {'size_x':model.size_x, 'size_y':model.size_y, 'size_z':model.size_z, 
        'Kx':getattr(model, 'Kx',.0), 'Ky':getattr(model, 'Ky',.0), 'Kz':getattr(model, 'Kz',.0)}
monitor1_Ex = AmplitudeMonitorVolume(comp=meep.Ex, **monitor_options) ## TODO try out how it differs with comp=meep.Dx - this should work, too

if not getattr(model, 'frequency_domain', None):       ## time-domain computation
    f.step()
    dt = (f.time()/c)
    meep_utils.lorentzian_unstable_check_new(model, dt)
    timer = meep_utils.Timer(simtime=model.simtime); meep.quiet(True) # use custom progress messages
    while (f.time()/c < model.simtime):                               # timestepping cycle
        f.step()
        timer.print_progress(f.time()/c)
        for monitor in (monitor1_Ex,): monitor.record(field=f)
    meep_utils.notify(model.simulation_name, run_time=timer.get_time())
else:                                       ## frequency-domain computation
    f.solve_cw(getattr(model, 'MaxTol',0.001), getattr(model, 'MaxIter', 5000), getattr(model, 'BiCGStab', 8)) 
    for monitor in (monitor1_Ex,): monitor.record(field=f)
    meep_utils.notify(model.simulation_name)

## Get the reflection and transmission of the structure
if meep.my_rank() == 0:
    # TODO update to new saving syntax, and test
    #meep_utils.savetxt(fname=model.simulation_name+".dat", fmt="%.6e",                            
            #X=zip(freq, np.abs(s11), np.angle(s11), np.abs(s12), np.angle(s12)),                  ## Save 5 columns: freq, amplitude/phase for reflection/transmission
            #header=model.parameterstring+columnheaderstring)     ## Export header

    headerstring = "#x-column Frequency [Hz]\n#Column Ex real\n#Column Ex imag\n"
    t, E = monitor1_Ex.get_waveforms()
    if not os.path.exists("cdh"): os.mkdir("cdh")
    meep_utils.savetxt(fname=os.path.join('cdh',model.simulation_name+".dat"), fmt="%.6e", 
            X=zip(t, E.real, E.imag), 
            header=model.parameterstring +  headerstring)
    with open("./last_simulation_name.dat", "w") as outfile: outfile.write(model.simulation_name) 

meep.all_wait()         # Wait until all file operations are finished
