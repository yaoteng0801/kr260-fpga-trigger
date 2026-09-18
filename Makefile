VIVADO ?= vivado
VIVADO_ENV ?= env -u PYTHONPATH
DTC ?= dtc
PYTHON ?= python3
MODE ?= trigger
JOBS ?= 8

ifeq ($(filter $(MODE),trigger loopback),)
$(error MODE must be trigger or loopback)
endif

.PHONY: all project bitstream overlays sim test hdf5-smoke clean

all: bitstream overlays

project:
	mkdir -p build/logs
	$(VIVADO_ENV) $(VIVADO) -mode batch -notrace \
		-journal build/logs/create_$(MODE).jou -log build/logs/create_$(MODE).log \
		-source hw/tcl/create_project.tcl -tclargs $(MODE)

bitstream: project
	mkdir -p build/logs
	$(VIVADO_ENV) $(VIVADO) -mode batch -notrace \
		-journal build/logs/build_$(MODE).jou -log build/logs/build_$(MODE).log \
		-source hw/tcl/build_bitstream.tcl -tclargs $(MODE) $(JOBS)

deploy/kr260-trigger.dtbo: device-tree/kr260-trigger.dts
	$(DTC) -@ -I dts -O dtb -o $@ $<

deploy/kr260-loopback.dtbo: device-tree/kr260-loopback.dts
	$(DTC) -@ -I dts -O dtb -o $@ $<

overlays: deploy/kr260-trigger.dtbo deploy/kr260-loopback.dtbo

sim:
	mkdir -p build/logs
	$(VIVADO_ENV) $(VIVADO) -mode batch -notrace \
		-journal build/logs/sim.jou -log build/logs/sim.log \
		-source hw/tcl/run_sim.tcl

test:
	$(PYTHON) -m pytest -q tests

hdf5-smoke:
	$(PYTHON) software/kr260_trigger.py Trigger_food_Data.h5 --sample bkg --count 20000 --software-only

clean:
	rm -rf build/vivado build/sim
	rm -f deploy/*.bit deploy/*.bin deploy/*.dtbo deploy/*.xsa
	rm -f reports/*.rpt reports/*_build_summary.txt
