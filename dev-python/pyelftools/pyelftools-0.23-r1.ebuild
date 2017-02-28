# Distributed under the terms of the GNU General Public License v2

EAPI="5"

PYTHON_COMPAT=( python2_7 python3_{4,5} )
inherit distutils-r1

DESCRIPTION="pure-Python library for analyzing ELF files and DWARF debugging information"
HOMEPAGE="https://pypi.python.org/pypi/pyelftools https://github.com/eliben/pyelftools"
SRC_URI="mirror://pypi/${PN:0:1}/${PN}/${P}.tar.gz"

LICENSE="public-domain"
SLOT="0"
KEYWORDS="*"
IUSE="examples"

python_test() {
	# readelf_tests often fails due to host `readelf` changing output format
	local t
	for t in all_unittests examples_test ; do
		"${PYTHON}" ./test/run_${t}.py || die "Tests fail with ${EPYTHON}"
	done
}

python_install_all() {
	use examples && local EXAMPLES=( examples/. )
	distutils-r1_python_install_all
}