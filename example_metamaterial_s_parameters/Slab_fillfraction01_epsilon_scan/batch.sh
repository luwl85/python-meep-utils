#!/bin/bash
if [ -z $NP ] ; then NP=2 ; fi             # number of processors
model=SphereArray
cellsize=300e-6
thz=1e12
#for eps in `seq 1 2 25 | tr , .`; do
	#mpirun -np $NP ../../scatter.py model=Slab fillfraction=.1 resolution=5u simtime=50p cellsize=$cellsize padding=10e-6 epsilon=$eps
	#../../effparam.py
#done

sharedoptions='effparam/*.dat --paramname epsilon --paramlabel '\$\\varepsilon_r\$' --figsizex 4 --figsizex 4 --xeval x/1e12 --ylim1 0'

../../plot_multiline.py $sharedoptions --xlabel "Frequency (THz)" --ycol 'imag N' \
   	--ylabel 'Refractive index $N_{\text{eff}}^{\prime\prime}$' --output ${PWD##*/}_ni.pdf \
	--paramlabel 'Permittivity' --contours yes --colormap gist_earth_r


