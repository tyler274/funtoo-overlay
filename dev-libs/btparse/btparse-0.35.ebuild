# Distributed under the terms of the GNU General Public License v2

EAPI="6"

DESCRIPTION="A C library to parse Bibtex files"
HOMEPAGE="http://www.gerg.ca/software/btOOL/"
SRC_URI="mirror://cpan/authors/id/A/AM/AMBS/btparse/${P}.tar.gz"

LICENSE="GPL-2"
SLOT="0"
KEYWORDS="*"
IUSE=""

DEPEND=""

src_install() {
       emake DESTDIR="${D}" install || die "emake install failed"
}

