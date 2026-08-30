APP_NAME  := Pink Page Count
APP_SRC   := packaging/dist/$(APP_NAME).app
APP_DEST  := /Applications/$(APP_NAME).app
ZIP_OUT   := packaging/dist/PinkPageCount-$(shell date +%Y-%m-%d).zip

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
	@echo "→ $(ZIP_OUT)"

send: install zip
	@open -R "$(ZIP_OUT)"

clean:
	rm -rf packaging/dist