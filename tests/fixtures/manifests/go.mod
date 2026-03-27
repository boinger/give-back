module github.com/example/myproject

go 1.21

require (
	github.com/gorilla/mux v1.8.0
	github.com/sirupsen/logrus v1.9.3
	golang.org/x/net v0.17.0
	github.com/stretchr/testify v1.8.4 // indirect
)

require github.com/spf13/cobra v1.7.0

replace github.com/example/localmod => ./localmod
replace github.com/example/othermod => ../othermod
