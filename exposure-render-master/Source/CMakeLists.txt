# Exposure Render: An interactive photo-realistic volume rendering framework
# Copyright (C) 2011 Thomas Kroes

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

cmake_minimum_required(VERSION 3.18)

PROJECT(ExposureRender LANGUAGES CXX CUDA)

set(CMAKE_CUDA_ARCHITECTURES 52 61 70 75 80 86 89)

# Add CUDA includes
INCLUDE_DIRECTORIES(
	${CMAKE_CURRENT_BINARY_DIR}
	${CMAKE_CURRENT_SOURCE_DIR}
)

# Export symbols
SET(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -D_EXPORTING")

# Make the "Core" source group
SOURCE_GROUP("Core" FILES ${vtkErCoreSources})

# General
SET(General
	device.h
	utilities.h
	geometry.h
	transport.h
	raymarching.h
	shader.h
	sample.h
	rng.h
	montecarlo.h
	ray.h
	volumes.h
	lights.h
	objects.h
	clippingobjects.h
	textures.h
	filter.h
	log.h
	defines.h
	camera.h
	procedural.h
	shape.h
	matrix.h
	vector.h
	buffer1d.h
	buffer2d.h
	buffer3d.h
	boundingbox.h
	transferfunction.h
	rendersettings.h
	timing.h
	exception.h
	enums.h
	color.h
	exposurerender.h
	exposurerender.cpp
	c_api.cpp
	tracer.h
	volume.h
	light.h
	scatterevent.h
	intersection.h
	object.h
	clippingobject.h
	texture.h
	bitmap.h
	buffer.h
	framebuffer.h
	pf.h
	plf.h
	pcf.h
	singlescattering.h
)

# General group
SOURCE_GROUP("General" FILES ${General})

# Shapes
SET(Shapes
	shapes.h
	plane.h
	box.h
	disk.h
	ring.h
	sphere.h
	cylinder.h
)

# Shapes group
SOURCE_GROUP("Shapes" FILES ${Shapes})

# API
SET(Bindable
	erbindable.h
	ertracer.h
	ervolume.h
	erlight.h
	erobject.h
	erclippingobject.h
	ertexture.h
	erbitmap.h
)

# API group
SOURCE_GROUP("Bindable" FILES ${Bindable})

# Filters
SET(Cuda
	singlescattering.cuh
	estimate.cuh
	gradientmagnitude.cuh
	filterrunningestimate.cuh
	filterframeestimate.cuh
	tonemap.cuh
	autofocus.cuh
	list.cuh
	wrapper.cuh
	macros.cuh
	core.cu
)

# Filters group
SOURCE_GROUP("Cuda" FILES ${Cuda})

# Make the library
ADD_LIBRARY(ErCore SHARED ${General} ${Shapes} ${Bindable} ${Cuda})
set_target_properties(ErCore PROPERTIES CUDA_SEPARABLE_COMPILATION ON)