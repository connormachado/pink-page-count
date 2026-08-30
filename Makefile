APP_NAME  := Pink Page Count
APP_SRC   := packaging/dist/$(APP_NAME).app
APP_DEST  := /Applications/$(APP_NAME).app
ZIP_OUT   := packaging/dist/PinkPageCount-$(shell date +%Y-%m-%d).zip

# DECISIONS.md 15.8. build_app.sh already gates the .app; this re-runs the same
# check over the zip, because the zip is the thing that actually gets AirDropped
# and REVIEW.md BLOCKER 1 was present in both.
CHECK     := packaging/check_deployment_target.py
TARGET    := 11.0
CHECK_PY  := $(firstword $(wildcard .venv-build/bin/python .venv/bin/python) python3)
# Not `uname -m`: /usr/local/bin/make is x86_64 and runs under Rosetta, where
# `uname -m` reports x86_64 too. See DECISIONS.md 15.8.
HOST_ARCH := $(if $(filter 1,$(shell sysctl -n hw.optional.arm64 2>/dev/null)),arm64,$(shell uname -m))

.DEFAULT_GOAL := build
.PHONY: build install zip send clean

build:
	./packaging/build_app.sh
	@test -d "$(APP_SRC)" || { echo "BUILD FAILED: $(APP_SRC) not produced"; exit 1; }

install: build
	@case "$(APP_DEST)" in /Applications/?*.app) ;; *) echo "refusing rm -rf on '$(APP_DEST)'"; exit 1;; esac
	-pkill -f "$(APP_NAME)"
	rm -rf "$(APP_DEST)"
	cp -R "$(APP_SRC)" "$(APP_DEST)"

zip: build
	rm -f "$(ZIP_OUT)"
	ditto -c -k --sequesterRsrc --keepParent "$(APP_SRC)" "$(ZIP_OUT)"
	"$(CHECK_PY)" "$(CHECK)" --max "$(TARGET)" --expect-arch "$(HOST_ARCH)" "$(ZIP_OUT)"
	@echo "→ $(ZIP_OUT)"

send: install zip
	@open -R "$(ZIP_OUT)"

clean:
	rm -rf packaging/dist