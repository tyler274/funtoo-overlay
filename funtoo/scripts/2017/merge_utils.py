#!/usr/bin/python3

import glob
import itertools
import os
import shutil
import subprocess
import sys
import datetime
import re
from lxml import etree
import portage
from portage.dbapi.porttree import portdbapi
from portage.dep import use_reduce, dep_getkey, flatten
from portage.versions import catpkgsplit
from portage.repository.config import RepoConfigLoader
from portage.exception import PortageKeyError

debug = False

mergeLog = open("/var/tmp/merge.log","w")

def get_pkglist(fname):
	if fname[0] == "/":
		cpkg_fn = fname
	else:
		cpkg_fn = os.path.dirname(os.path.abspath(__file__)) + "/" + fname
	if not os.path.isdir(cpkg_fn):
		# single file specified
		files = [ cpkg_fn ]
	else:
		# directory specifed -- we will grab the file contents of the dir:
		fn_list = os.listdir(cpkg_fn)
		fn_list.sort()
		files = []
		for fn in fn_list:
			files.append(cpkg_fn + "/" + fn)
	patterns = []
	for cpkg_fn in files:
		with open(cpkg_fn,"r") as cpkg:
			for line in cpkg:
				line = line.strip()
				if line == "":
					continue
				ls = line.split("#")
				if len(ls) >=2:
					line = ls[0]
				patterns.append(line)
	else:
		return patterns

def filterInCategory(pkgset, fil):
	match = set()
	nomatch = set()
	for pkg in list(pkgset):
		if pkg.startswith(fil):
			match.add(pkg)
		else:
			nomatch.add(pkg)
	return match, nomatch

def getDependencies(cur_overlay, catpkgs, levels=0, cur_level=0):
	cur_tree = cur_overlay.root
	try:
		with open(os.path.join(cur_tree, 'profiles/repo_name')) as f:
			cur_name = f.readline().strip()
	except FileNotFoundError:
			cur_name = cur_overlay.name
	env = os.environ.copy()
	env['PORTAGE_REPOSITORIES'] = '''
[DEFAULT]
main-repo = %s 

[%s]
location = %s
''' % (cur_name, cur_name, cur_tree)
	p = portage.portdbapi(mysettings=portage.config(env=env,config_profile_path=''))
	p.frozen = False
	mypkgs = set()
	for catpkg in list(catpkgs):
		for pkg in p.cp_list(catpkg):
			if pkg == '':
				print("No match for %s" % catpkg)
				continue
			try:
				aux = p.aux_get(pkg, ["DEPEND", "RDEPEND"])
			except PortageKeyError:
				print("Portage key error for %s" % repr(pkg))
				return mypkgs
			for dep in flatten(use_reduce(aux[0]+" "+aux[1], matchall=True)):
				if len(dep) and dep[0] == "!":
					continue
				try:
					mypkg = dep_getkey(dep)
				except portage.exception.InvalidAtom:
					continue
				if mypkg not in mypkgs:
					mypkgs.add(mypkg)
				if levels != cur_level:
					mypkgs = mypkgs.union(getDependencies(cur_overlay, mypkg, levels=levels, cur_level=cur_level+1))
	return mypkgs

def getPackagesInCatWithEclass(cur_overlay, cat, eclass):
	cur_tree = cur_overlay.root
	try:
		with open(os.path.join(cur_tree, 'profiles/repo_name')) as f:
			cur_name = f.readline().strip()
	except FileNotFoundError:
			cur_name = cur_overlay.name
	env = os.environ.copy()
	env['PORTAGE_REPOSITORIES'] = '''
[DEFAULT]
main-repo = %s

[%s]
location = %s
''' % (cur_name, cur_name, cur_tree)
	p = portage.portdbapi(mysettings=portage.config(env=env, config_profile_path=''))
	p.frozen = False
	mypkgs = set()
	for catpkg in p.cp_all(categories=[cat]):
		for pkg in p.cp_list(catpkg):
			if pkg == '':
				print("No match for %s" % catpkg)
				continue
			try:
				aux = p.aux_get(pkg, ["INHERITED"])
			except PortageKeyError:
				print("Portage key error for %s" % repr(pkg))
				continue
			if eclass in aux[0].split():
				if eclass not in mypkgs:
					mypkgs.add(catpkg)
	return mypkgs

def repoName(cur_overlay):
	cur_tree = cur_overlay.root
	try:
		with open(os.path.join(cur_tree, 'profiles/repo_name')) as f:
			cur_name = f.readline().strip()
	except FileNotFoundError:
			cur_name = cur_overlay.name
	return cur_name

def getAllEclasses(ebuild_repo, super_repo=None):
	return getAllMeta("INHERITED", ebuild_repo=ebuild_repo, super_repo=super_repo)

def getAllLicenses(ebuild_repo, super_repo=None):
	return getAllMeta("LICENSE", ebuild_repo=ebuild_repo, super_repo=super_repo)


def getAllMeta(metadata, ebuild_repo, super_repo=None):
	print("EBUILD REPO", ebuild_repo.root, "SUPER_REPO", super_repo.root)
	metadict = { "LICENSE" : 0, "INHERITED" : 1 }
	metapos = metadict[metadata]

	# ebuild_repo is where we get the set of all packages for our loop:
	eb_name = ebuild_repo.reponame if ebuild_repo.reponame else repoName(ebuild_repo)
	env = os.environ.copy()
	# super_repo contains all ebuilds in ebuild_repo AND eclasses
	if super_repo:
		super_name = super_repo.reponame if super_repo.reponame else repoName(super_repo)
		env['PORTAGE_REPOSITORIES'] = '''
[DEFAULT]
main-repo = gentoo

[gentoo]
location = %s

[%s]
location = %s
eclass-overrides = gentoo 
aliases = -gentoo
masters = gentoo 
	''' % ( super_repo.root, eb_name, ebuild_repo.root)
	else:
		env['PORTAGE_REPOSITORIES'] = '''
[DEFAULT]
main-repo = %s

[%s]
location = %s
	''' % ( eb_name, eb_name, eb_name, ebuild_repo.root )
	print(env['PORTAGE_REPOSITORIES'])
	p = portdbapi(mysettings=portage.config(env=env,config_profile_path=''))
	p.frozen = False
	myeclasses = set()
	for cp in p.cp_all(trees=[ebuild_repo.root]):
		for cpv in p.cp_list(cp, mytree=ebuild_repo.root):
			try:
				aux = p.aux_get(cpv, ["LICENSE","INHERITED"], mytree=ebuild_repo.root)
			except PortageKeyError:
				print("Portage key error for %s" % repr(cpv))
				raise
			if metadata == "INHERITED":
				for eclass in aux[metapos].split():
					key = eclass + ".eclass"
					if key not in myeclasses:
						myeclasses.add(key)
			elif metadata == "LICENSE":
				for lic in aux[metapos].split():
					if lic not in myeclasses:
						myeclasses.add(lic)
	return myeclasses

def generateAuditSet(name, from_tree, pkgdir=None, branch="master", catpkg_dict=None):

	# This function is similar to generateShardSteps, but it doesn't actually generate steps. Instead
	# it runs through the same package list, and generates a set of catpkgs (ignoring eclass commands)
	# that would be copied. Then we can compare against the catpkgs that actually exist in a repository
	# and see if any are missing. 

	all_pats = []
	pkgf = "package-sets/%s-packages" % name
	if pkgdir != None:
		pkgf = pkgdir + "/" + pkgf
	for pattern in get_pkglist(pkgf):
		if pattern.startswith("@regex@:"):
			all_pats.append(re.compile(pattern[8:]))
		elif pattern.startswith("@depsincat@:"):
			patsplit = pattern.split(":")
			catpkg = patsplit[1]
			dep_pkglist = getDependencies(from_tree, [ catpkg ] )
			if len(patsplit) == 3:
				dep_pkglist, dep_pkglist_nomatch = filterInCategory(dep_pkglist, patsplit[2])
			all_pats += list(dep_pkglist)
		elif pattern.startswith("@cat_has_eclass@:"):
			patsplit = pattern.split(":")
			cat, eclass = patsplit[1:]
			cat_pkglist = getPackagesInCatWithEclass(from_tree, cat, eclass )
			all_pats += list(cat_pkglist)
		elif pattern == "@all_eclasses@":
			pass
		elif pattern.startswith("@eclass@:"):
			pass
		else:
			all_pats.append(pattern)
	catpkgs = set()
	all_catpkgs = from_tree.getAllCatPkgs()
	all_catpkgs_set = set(all_catpkgs)
	prev_catpkgs = set(catpkg_dict.keys())
	for pat in all_pats:
		if isinstance(pat, regextype):
			for cp in all_catpkgs:
				m = pat.match(cp)
				if m and cp not in prev_catpkgs:
					catpkgs.add(cp)
		elif pat.endswith("/*"):
			ps = pat.split("/")
			cat = ps[0]
			for cp in all_catpkgs:
				cps = cp.split("/")
				if len(cps) and cps[0] == cat and cp not in prev_catpkgs:
					catpkgs.add(cp)
		else:
			if pat in all_catpkgs_set and pat not in prev_catpkgs:
				catpkgs.add(pat)
	for cp in list(catpkgs):
		catpkg_dict[cp] = name
	return catpkgs

def generateShardSteps(name, from_tree, to_tree, pkgdir=None, branch="master", catpkg_dict=None):
	steps = []
	if branch:
		steps += [ GitCheckout(branch) ]
	pkglist = []
	pkgf = "package-sets/%s-packages" % name
	pkgf_skip = "package-sets/%s-skip" % name
	if pkgdir != None:
		pkgf = pkgdir + "/" + pkgf
		pkgf_skip = pkgdir + "/" + pkgf_skip
	skip = []
	if os.path.exists(pkgf_skip):
		skip = get_pkglist(pkgf_skip)
	for pattern in get_pkglist(pkgf):
		if pattern.startswith("@regex@:"):
			steps += [ InsertEbuilds(from_tree, select=re.compile(pattern[8:]), skip=skip, replace=True, catpkg_dict=catpkg_dict) ]
		elif pattern.startswith("@depsincat@:"):
			patsplit = pattern.split(":")
			catpkg = patsplit[1]
			dep_pkglist = getDependencies(from_tree, [ catpkg ] )
			if len(patsplit) == 3:
				dep_pkglist, dep_pkglist_nomatch = filterInCategory(dep_pkglist, patsplit[2])
			pkglist += list(dep_pkglist)
		elif pattern.startswith("@cat_has_eclass@:"):
			patsplit = pattern.split(":")
			cat, eclass = patsplit[1:]
			cat_pkglist = getPackagesInCatWithEclass(from_tree, cat, eclass )
			pkglist += list(cat_pkglist)
		elif pattern == "@all_eclasses@":
			# copy over all eclasses used by all ebuilds
			# get all eclasses used in ebuilds in to_tree, and copy them from from_tree to to_tree
			a = getAllEclasses(ebuild_repo=to_tree, super_repo=from_tree)
			steps += [ InsertEclasses(from_tree, select=list(a)) ]
		elif pattern.startswith("@eclass@:"):
			steps += [ InsertEclasses(from_tree, select=re.compile(pattern[9:])) ]
		else:
			pkglist.append(pattern)
	if pkglist:
		steps += [ InsertEbuilds(from_tree, select=pkglist, skip=skip, replace=True, catpkg_dict=catpkg_dict) ]
	return steps

def qa_build(host,build,arch_desc,subarch,head,target):
	success = False
	print("Performing remote QA build on %s for %s %s %s %s (%s)" % (host, build, arch_desc, subarch, head, target))
	build_dir = datetime.datetime.now().strftime("%Y-%m-%d") + "-" + head
	exists = subprocess.getoutput("ssh %s '[ -e /home/mirror/funtoo/%s/%s/%s/" % ( host, build, arch_desc, subarch ) + build_dir + "/status ] && echo yep || echo nope'") == "yep"
	if not exists:
		status = subprocess.call(["/usr/bin/ssh",host,"/root/metro/scripts/ezbuild.sh", build, arch_desc, subarch, target, build_dir])
		if status:
			print("ezbuild.sh completed with errors.")
	success = subprocess.getoutput("ssh %s cat /home/mirror/funtoo/%s/%s/%s/" % ( host, build, arch_desc, subarch )  + build_dir + "/status") == "ok"
	if success:
		print("Build successful.")
	else:
		print("Build FAILED.")
	return success

def headSHA1(tree):
	head = None
	hfile = os.path.join(tree,".git/HEAD")
	if os.path.exists(hfile):
		infile = open(hfile,"r")
		line = infile.readline()
		infile.close()
		if len(line.split(":")) == 2:
			head = line.split()[1]
			hfile2 = os.path.join(tree,".git")
			hfile2 = os.path.join(hfile2,head)
			if os.path.exists(hfile2):
				infile = open(hfile2,"r")
				head = infile.readline().split()[0]
		else:
			head=line.strip()
	return head

def runShell(string,abortOnFail=True):
	if debug:
		print(string)
	else:
		print("running: %r" % string)
		out = subprocess.getstatusoutput(string)
		if out[0] != 0:
			print("Error executing %r" % string)
			print()
			print("output:")
			print(out[1])
			if abortOnFail:
				sys.exit(1)
			else:
				return False
	return True

def run_command(args, *, abort_on_failure=True, **kwargs):
	if debug:
		print(args)
	else:
		print("running: %r" % args)
		stdout = kwargs.pop("stdout", subprocess.PIPE)
		stderr = kwargs.pop("stderr", subprocess.PIPE)
		try:
			with subprocess.Popen(args, stdout=stdout, stderr=stderr, **kwargs) as process:
				status = process.wait()
				stdout_content = process.stdout.read().decode()
				stderr_content = process.stderr.read().decode()
		except OSError as e:
			status = -1
			stdout_content = ""
			stderr_content = e.strerror
		if status != 0:
			print("Error executing %r" % args)
			print()
			print("stdout: %s" % stdout_content)
			print("stderr: %s" % stderr_content)
			if abort_on_failure:
				sys.exit(1)
			else:
				return False
	return True

class MergeStep(object):
	pass

class AutoGlobMask(MergeStep):

	"""
	AutoGlobMask will automatically create a package.mask file that matches particular
	ebuilds that it finds in the tree.

	catpkg: The catpkg to process. AutoGlobMask will look into the destination tree in
	this catpkg directory.

	glob: the wildcard pattern of an ebuild files to match in the catpkg directory.

	maskdest: The filename of the mask file to create in profiles/packages.mask.

	All ebuilds matching glob in the catpkg dir will have mask entries created and
	written to profiles/package.mask/maskdest.

	"""

	def __init__(self,catpkg,glob,maskdest):
		self.glob = glob
		self.catpkg = catpkg
		self.maskdest = maskdest

	def run(self,tree):
		if not os.path.exists(tree.root + "/profiles/package.mask"):
			os.makedirs(tree.root + "/profiles/package.mask")
		f = open(os.path.join(tree.root,"profiles/package.mask", self.maskdest), "w")
		os.chdir(os.path.join(tree.root,self.catpkg))
		cat = self.catpkg.split("/")[0]
		for item in glob.glob(self.glob+".ebuild"):
			f.write("=%s/%s\n" % (cat,item[:-7]))
		f.close()

class ThirdPartyMirrors(MergeStep):
	"Add funtoo's distfiles mirror, and add funtoo's mirrors as gentoo back-ups."

	def run(self,tree):
		orig = "%s/profiles/thirdpartymirrors" % tree.root
		new = "%s/profiles/thirdpartymirrors.new" % tree.root
		mirrors = "http://build.funtoo.org/distfiles http://ftp.osuosl.org/pub/funtoo/distfiles https://distfiles.ceresia.ch/distfiles"
		a = open(orig, "r")
		b = open(new, "w")
		for line in a:
			ls = line.split()
			if len(ls) and ls[0] == "gentoo":

				# Add funtoo mirrors as second and third Gentoo mirrors. So, try the main gentoo mirror first.
				# If not there, maybe we forked it and the sources are removed from Gentoo's mirrors, so try
				# ours. This allows us to easily fix mirroring issues for users.

				b.write("gentoo\t"+ls[1]+" "+mirrors+" "+" ".join(ls[2:])+"\n")
			else:
				b.write(line)
		b.write("funtoo %s\n" % mirrors)
		a.close()
		b.close()
		os.unlink(orig)
		os.link(new, orig)
		os.unlink(new)

class ApplyPatchSeries(MergeStep):
	def __init__(self,path):
		self.path = path

	def run(self,tree):
		a = open(os.path.join(self.path,"series"),"r")
		for line in a:
			if line[0:1] == "#":
				continue
			if line[0:4] == "EXEC":
				ls = line.split()
				runShell( "( cd %s; %s/%s )" % ( tree.root, self.path, ls[1] ))
			else:
				runShell( "( cd %s; git apply %s/%s )" % ( tree.root, self.path, line[:-1] ))

class GenerateRepoMetadata(MergeStep):
	def __init__(self, name, masters=[], aliases=[], priority=None):
		self.name = name
		self.aliases = aliases
		self.masters = masters
		self.priority = priority

	def run(self,tree):
		meta_path = os.path.join(tree.root, "metadata")
		if not os.path.exists(meta_path):
			os.makedirs(meta_path)
		a = open(meta_path + '/layout.conf','w')
		out = '''repo-name = %s
thin-manifests = true
sign-manifests = false
profile-formats = portage-2
cache-formats = md5-dict
''' % self.name
		if self.aliases:
			out += "aliases = %s\n" % " ".join(self.aliases)
		if self.masters:
			out += "masters = %s\n" % " ".join(self.masters)
		a.write(out)
		a.close()
		rn_path = os.path.join(tree.root, "profiles")
		if not os.path.exists(rn_path):
			os.makedirs(rn_path)
		a = open(rn_path + '/repo_name', 'w')
		a.write(self.name + "\n")
		a.close() 

class RemoveFiles(MergeStep):
	def __init__(self,globs=[]):
		self.globs = globs
	
	def run(self,tree):
		for glob in self.globs:
			cmd = "rm -rf %s/%s" % ( tree.root, glob )
			runShell(cmd)

class SyncDir(MergeStep):
	def __init__(self,srcroot,srcdir=None,destdir=None,exclude=[],delete=False):
		self.srcroot = srcroot
		self.srcdir = srcdir
		self.destdir = destdir
		self.exclude = exclude
		self.delete = delete

	def run(self,tree):
		if self.srcdir:
			src = os.path.join(self.srcroot,self.srcdir)+"/"
		else:
			src = os.path.normpath(self.srcroot)+"/"
		if self.destdir:
			dest = os.path.join(tree.root,self.destdir)+"/"
		else:
			if self.srcdir:
				dest = os.path.join(tree.root,self.srcdir)+"/"
			else:
				dest = os.path.normpath(tree.root)+"/"
		if not os.path.exists(dest):
			os.makedirs(dest)
		cmd = "rsync -a --exclude CVS --exclude .svn --filter=\"hide /.git\" --filter=\"protect /.git\" "
		for e in self.exclude:
			cmd += "--exclude %s " % e
		if self.delete:
			cmd += "--delete --delete-excluded "
		cmd += "%s %s" % ( src, dest )
		runShell(cmd)

class CopyAndRename(MergeStep):
	def __init__(self, src, dest, ren_fun):
		self.src = src
		self.dest = dest
		#renaming function ... accepts source file path, and returns destination filename
		self.ren_fun = ren_fun

	def run(self, tree):
		srcpath = os.path.join(tree.root,self.src)
		for f in os.listdir(srcpath):
			destfile = os.path.join(tree.root,self.dest)
			destfile = os.path.join(destfile,self.ren_fun(f))
			runShell("( cp -a %s/%s %s )" % ( srcpath, f, destfile ))

class SyncFiles(MergeStep):
	def __init__(self, srcroot, files):
		self.srcroot = srcroot
		self.files = files
		if not isinstance(files, dict):
			raise TypeError("'files' argument should be a dict of source:destination items")

	def run(self, tree):
		for src, dest in self.files.items():
			if dest is not None:
				dest = os.path.join(tree.root, dest)
			else:
				dest = os.path.join(tree.root, src)
			src = os.path.join(self.srcroot, src)
			if os.path.exists(dest):
				print("%s exists, attempting to unlink..." % dest)
				try:
					os.unlink(dest)
				except:
					pass
			dest_dir = os.path.dirname(dest)
			if os.path.exists(dest_dir) and os.path.isfile(dest_dir):
				os.unlink(dest_dir)
			if not os.path.exists(dest_dir):
				os.makedirs(dest_dir)
			print("copying %s to final location %s" % (src, dest))
			shutil.copyfile(src, dest)

class MergeUpdates(MergeStep):
	def __init__(self, srcroot):
		self.srcroot = srcroot

	def run(self, tree):
		for src in sorted(glob.glob(os.path.join(self.srcroot, "profiles/updates/?Q-????")), key=lambda x: (x[-4:], x[-7])):
			dest = os.path.join(tree.root, "profiles/updates", src[-7:])
			if os.path.exists(dest):
				src_file = open(src)
				dest_file = open(dest)
				src_lines = src_file.readlines()
				dest_lines = dest_file.readlines()
				src_file.close()
				dest_file.close()
				dest_lines.extend(src_lines)
				dest_file = open(dest, "w")
				dest_file.writelines(dest_lines)
				dest_file.close()
			else:
				shutil.copyfile(src, dest)

class CleanTree(MergeStep):
	# remove all files from tree, except dotfiles/dirs.

	def __init__(self,exclude=[]):
		self.exclude = exclude
	def run(self,tree):
		for fn in os.listdir(tree.root):
			if fn[:1] == ".":
				continue
			if fn in self.exclude:
				continue
			runShell("rm -rf %s/%s" % (tree.root, fn))

class SyncFromTree(SyncDir):
	# sync a full portage tree, deleting any excess files in the target dir:
	def __init__(self,srctree,exclude=[]):
		self.srctree = srctree
		SyncDir.__init__(self,srctree.root,srcdir=None,destdir=None,exclude=exclude,delete=True)

	def run(self,desttree):
		SyncDir.run(self,desttree)
		desttree.logTree(self.srctree)

class Tree(object):
	def __init__(self,name,root):
		self.name = name
		self.root = root
	def head(self):
		return "None"

class GitTree(Tree):

	"A Tree (git) that we can use as a source for work jobs, and/or a target for running jobs."

	def __init__(self,name, branch="master",url=None,commit=None,pull=False,root=None,xml_out=None,initialize=False,reponame=None):
		self.name = name
		self.root = root
		self.branch = branch
		print("SET BRANCH TO", self.branch)
		self.commit = commit
		self.url = url
		self.merged = []
		self.xml_out = xml_out
		self.push = False
		self.changes = True
		self.reponame = reponame
		# if we don't specify root destination tree, assume we are source only:
		if self.root == None:
			self.writeTree = False
			if self.url == None:
				print("Error: please specify root or url for GitTree.")
				sys.exit(1)
			base = "/var/git/source-trees"
			self.root = "%s/%s" % ( base, self.name )
			if os.path.exists(self.root):
				self.head_old = self.head()
				runShell("(cd %s; git fetch origin)" % self.root, abortOnFail=False)
				runShell("(cd %s; git checkout %s)" % ( self.root, self.branch ))
				if pull:
					runShell("(cd %s; git pull -f origin %s)" % ( self.root, self.branch ), abortOnFail=False)
				self.head_new = self.head()
				self.changes = self.head_old != self.head_new
			else:
				if not os.path.exists(base):
					os.makedirs(base)
				if url:
					runShell("(cd %s; git clone %s %s)" % ( base, self.url, self.name ))
					runShell("(cd %s; git checkout %s)" % ( self.root, self.branch ))
				else:
					print("Error: tree %s does not exist, but no clone URL specified. Exiting." % self.root)
					sys.exit(1)
		else:
			self.writeTree = True
			if not os.path.isdir("%s/.git" % self.root):
				if not initialize:
					print("Error: repository does not exist at %s. Exiting." % self.root)
					sys.exit(1)
				else:
					if os.path.exists(self.root):
						print("Repository %s: --init specified but path already exists. Exiting.")
						sys.exit(1)
					os.makedirs(self.root)
					runShell("( cd %s; git init )" % self.root )
					runShell("echo 'created by merge.py' > %s/README" % self.root )
					runShell("( cd %s; git add README; git commit -a -m 'initial commit by merge.py' )" % self.root )
					if isinstance(initialize, str):
						if not runShell("( cd %s; git checkout -b %s; git rm -f README; git commit -a -m 'initial %s commit' )" % (self.root,initialize,initialize),abortOnFail=False ):
							print("Git repository creation failed, removing.")
							runShell("( rm -f %s )" % self.root)
							sys.exit(1)
			else:
				self.push = True
		# branch is updated -- now switch to specific commit if one was specified:
		if self.commit:
			runShell("(cd %s; git checkout %s)" % ( self.root, self.commit ))

	def getAllCatPkgs(self):
		self.gitCheckout()
		with open(self.root + "/profiles/categories","r") as a:
			cats = a.read().split()
		catpkgs = {} 
		for cat in cats:
			if not os.path.exists(self.root + "/" + cat):
				continue
			pkgs = os.listdir(self.root + "/" + cat)
			for pkg in pkgs:
				if not os.path.isdir(self.root + "/" + cat + "/" + pkg):
					continue
				catpkgs[cat + "/" + pkg] = self.name
		return catpkgs

	def gitCheckout(self,branch="master"):
		runShell("(cd %s; git checkout %s)" % ( self.root, self.branch ))

	def gitCommit(self,message="",upstream="origin",branch=None,push=True):
		if branch == None:
			branch = self.branch
		runShell("( cd %s; git add . )" % self.root )
		cmd = "( cd %s; [ -n \"$(git status --porcelain)\" ] && git commit -a -F - << EOF || exit 0\n" % self.root
		if message != "":
			cmd += "%s\n\n" % message
		names = []
		if len(self.merged):
			cmd += "merged: \n\n"
			for name, sha1 in self.merged:
				if name in names:
					# don't print dups
					continue
				names.append(name)
				if sha1 != None:
					cmd += "  %s: %s\n" % ( name, sha1 )
		cmd += "EOF\n"
		cmd += ")\n"
		print("running: %s" % cmd)
		# we use os.system because this multi-line command breaks runShell() - really, breaks commands.getstatusoutput().
		retval = os.system(cmd)
		if retval != 0:
			print("Commit failed.")
			sys.exit(1)
		if branch != False and push == True:
			runShell("(cd %s; git push %s %s)" % ( self.root, upstream, branch ))
		else:	 
			print("Pushing disabled.")


	def run(self,steps):
		print("Starting run")
		for step in steps:
			if step != None:
				print("Running step", step.__class__.__name__)
				step.run(self)

	def head(self):
		if self.commit:
			return self.commit
		else:
			return headSHA1(self.root)

	def logTree(self,srctree):
		# record name and SHA of src tree in dest tree, used for git commit message/auditing:
		if srctree.name == None:
			# this tree doesn't have a name, so just copy any existing history from that tree
			self.merged.extend(srctree.merged)
		else:
			# this tree has a name, so record the name of the tree and its SHA1 for reference
			if hasattr(srctree, "origroot"):
				self.merged.append([srctree.name, headSHA1(srctree.origroot)])
				return

			self.merged.append([srctree.name, srctree.head()])

class RsyncTree(Tree):
	def __init__(self,name,url="rsync://rsync.us.gentoo.org/gentoo-portage/"):
		self.name = name
		self.url = url 
		base = "/var/rsync/source-trees"
		self.root = "%s/%s" % (base, self.name)
		if not os.path.exists(base):
			os.makedirs(base)
		runShell("rsync --recursive --delete-excluded --links --safe-links --perms --times --compress --force --whole-file --delete --timeout=180 --exclude=/.git --exclude=/metadata/cache/ --exclude=/metadata/glsa/glsa-200*.xml --exclude=/metadata/glsa/glsa-2010*.xml --exclude=/metadata/glsa/glsa-2011*.xml --exclude=/metadata/md5-cache/	--exclude=/distfiles --exclude=/local --exclude=/packages %s %s/" % (self.url, self.root))

class SvnTree(Tree):
	def __init__(self, name, url=None):
		self.name = name
		self.url = url
		base = "/var/svn/source-trees"
		self.root = "%s/%s" % (base, self.name)
		if not os.path.exists(base):
			os.makedirs(base)
		if os.path.exists(self.root):
			runShell("(cd %s; svn up)" % self.root, abortOnFail=False)
		else:
			runShell("(cd %s; svn co %s %s)" % (base, self.url, self.name))

class CvsTree(Tree):
	def __init__(self, name, url=None, path=None):
		self.name = name
		self.url = url
		if path is None:
			path = self.name
		base = "/var/cvs/source-trees"
		self.root = "%s/%s" % (base, path)
		if not os.path.exists(base):
			os.makedirs(base)
		if os.path.exists(self.root):
			runShell("(cd %s; cvs update -dP)" % self.root, abortOnFail=False)
		else:
			runShell("(cd %s; cvs -d %s co %s)" % (base, self.url, path))

regextype = type(re.compile('hello, world'))

class InsertFilesFromSubdir(MergeStep):

	def __init__(self,srctree,subdir,suffixfilter=None,select="all",skip=None):
		self.subdir = subdir
		self.suffixfilter = suffixfilter
		self.select = select
		self.srctree = srctree
		self.skip = skip 

	def run(self,desttree):
		desttree.logTree(self.srctree)

		src = os.path.join(self.srctree.root, self.subdir)
		if not os.path.exists(src):
			print("Eclass dir %s does not exist; skipping %s insertion..." % (src, self.subdir))
			return
		dst = os.path.join(desttree.root, self.subdir)
		if not os.path.exists(dst):
			os.makedirs(dst)
		for e in os.listdir(src):
			if self.suffixfilter and not e.endswith(self.suffixfilter):
				continue
			if isinstance(self.select, list):
				if e not in self.select:
					continue
			elif isinstance(self.select, regextype):
				if not self.select.match(e):
					continue
			if isinstance(self.skip, list):
				if e in self.skip:
					continue
			elif isinstance(self.skip, regextype):
				if self.skip.match(e):
					continue
			runShell("cp -a %s/%s %s" % ( src, e, dst))

class InsertEclasses(InsertFilesFromSubdir):

	def __init__(self,srctree,select="all",skip=None):
		InsertFilesFromSubdir.__init__(self,srctree,"eclass",".eclass",select=select,skip=skip)

class InsertLicenses(InsertFilesFromSubdir):

	def __init__(self,srctree,select="all",skip=None):
		InsertFilesFromSubdir.__init__(self,srctree,"licenses",select=select,skip=skip)

class CreateCategories(MergeStep):

	def __init__(self,srctree):
		self.srctree = srctree

	def run(self,desttree):
		catset = set()
		with open(self.srctree.root + "/profiles/categories", "r") as f:
			cats = f.read().split()
			for cat in cats:
				if os.path.isdir(desttree.root + "/" + cat):
					catset.add(cat)
			if not os.path.exists(desttree.root + "/profiles"):
				os.makedirs(desttree.root + "/profiles")
			with open(desttree.root + "/profiles/categories", "w") as g:
				for cat in sorted(list(catset)):
					g.write(cat+"\n")

class ZapMatchingEbuilds(MergeStep):
	def __init__(self,srctree,select="all",branch=None):
		self.select = select
		self.srctree = srctree
		if branch != None:
			# Allow dynamic switching to different branches/commits to grab things we want:
			self.srctree.gitCheckout(branch)

	def run(self,desttree):
		# Figure out what categories to process:
		dest_cat_path = os.path.join(desttree.root, "profiles/categories")
		if os.path.exists(dest_cat_path):
			with open(dest_cat_path, "r") as f:
				dest_cat_set = set(f.read().splitlines())
		else:
			dest_cat_set = set()

		# Our main loop:
		print( "# Zapping builds from %s" % desttree.root )
		for cat in os.listdir(desttree.root):
			if cat not in dest_cat_set:
				continue
			src_catdir = os.path.join(self.srctree.root,cat)
			if not os.path.isdir(src_catdir):
				continue
			for src_pkg in os.listdir(src_catdir):
				dest_pkgdir = os.path.join(desttree.root,cat,src_pkg)
				if not os.path.exists(dest_pkgdir):
					# don't need to zap as it doesn't exist
					continue
				runShell("rm -rf %s" % dest_pkgdir)

class InsertEbuilds(MergeStep):

	"""
	Insert ebuilds in source tre into destination tree.

	select: Ebuilds to copy over.
		By default, all ebuilds will be selected. This can be modified by setting select to a
		list of ebuilds to merge (specify by catpkg, as in "x11-apps/foo"). It is also possible
		to specify "x11-apps/*" to refer to all source ebuilds in a particular category.

	skip: Ebuilds to skip.
		By default, no ebuilds will be skipped. If you want to skip copying certain ebuilds,
		you can specify a list of ebuilds to skip. Skipping will remove additional ebuilds from
		the set of selected ebuilds. Specify ebuilds to skip using catpkg syntax, ie.
		"x11-apps/foo". It is also possible to specify "x11-apps/*" to skip all ebuilds in
		a particular category.

	replace: Ebuilds to replace.
		By default, if an catpkg dir already exists in the destination tree, it will not be overwritten.
		However, it is possible to change this behavior by setting replace to True, which means that
		all catpkgs should be overwritten. It is also possible to set replace to a list containing
		catpkgs that should be overwritten. Wildcards such as "x11-libs/*" will be respected as well.

	merge: Merge source/destination ebuilds. Default = None.
		If a source catpkg is going to replace a destination catpkg, and this behavior is not desired,
		you can use merge to tell InsertEbuilds to add the source ebuilds "on top of" the existing
		ebuilds. The Manifest file will be updated appropriately. Possible values are None (don't
		do merging), True (if dest catpkg exists, *always* merge new ebuilds on top), or a list containing
		catpkg atoms, with wildcards like "x11-apps/*" being recognized. Note that if merging is
		enabled and identical ebuild versions exist, then the version in the source repo will replace
		the version in the destination repo.

	categories: Categories to process. 
		categories to process for inserting ebuilds. Defaults to all categories in tree, using
		profiles/categories and all dirs with "-" in them and "virtuals" as sources.
	
	
	"""
	def __init__(self,srctree,select="all",skip=None,replace=False,merge=None,categories=None,ebuildloc=None,branch=None,catpkg_dict=None):
		self.select = select
		self.skip = skip
		self.srctree = srctree
		self.replace = replace
		self.merge = merge
		self.categories = categories
		self.catpkg_dict = catpkg_dict
		if self.catpkg_dict == None:
			self.catpkg_dict = {}

		if branch != None:
			# Allow dynamic switching to different branches/commits to grab things we want:
			self.srctree.gitCheckout(branch)

		self.ebuildloc = ebuildloc

	def __repr__(self):
		if self.select:
			return "<InsertEbuilds: %s>" % " ".join(self.select) if type(self.select) == list else ""
		else:
			return "<InsertEbuilds>"

	def run(self,desttree):
		if self.ebuildloc:
			srctree_root = self.srctree.root + "/" + self.ebuildloc
		else:
			srctree_root = self.srctree.root
		desttree.logTree(self.srctree)
		# Figure out what categories to process:
		src_cat_path = os.path.join(srctree_root, "profiles/categories")
		dest_cat_path = os.path.join(desttree.root, "profiles/categories")
		if self.categories != None:
			# categories specified in __init__:
			src_cat_set = set(self.categories)
		else:
			src_cat_set = set()
			if os.path.exists(src_cat_path):
				# categories defined in profile:
				with open(src_cat_path, "r") as f:
					src_cat_set.update(f.read().splitlines())
			# auto-detect additional categories:
			cats = os.listdir(srctree_root)
			for cat in cats:
				# All categories have a "-" in them and are directories:
				if os.path.isdir(os.path.join(srctree_root,cat)):
					if "-" in cat or cat == "virtual":
						src_cat_set.add(cat)
		if os.path.exists(dest_cat_path):
			with open(dest_cat_path, "r") as f:
				dest_cat_set = set(f.read().splitlines())
		else:
			dest_cat_set = set()

		# Our main loop:
		print( "# Merging in ebuilds from %s" % srctree_root )
		for cat in src_cat_set:
			catdir = os.path.join(srctree_root, cat)
			if not os.path.isdir(catdir):
				# not a valid category in source overlay, so skip it
				continue
			#runShell("install -d %s" % catdir)
			catall = "%s/*" % cat
			for pkg in os.listdir(catdir):
				catpkg = "%s/%s" % (cat,pkg)
				pkgdir = os.path.join(catdir, pkg)
				if catpkg in self.catpkg_dict:
					#already copied
					continue
				if not os.path.isdir(pkgdir):
					# not a valid package dir in source overlay, so skip it
					continue
				if isinstance(self.select, list):
					if (catall not in self.select) and (catpkg not in self.select):
						# we have a list of pkgs to merge, and this isn't on the list, so skip:
						continue
				elif isinstance(self.select, regextype):
					if not self.select.match(catpkg):
						# no regex match:
						continue
				if isinstance(self.skip, list):
					if ((catpkg in self.skip) or (catall in self.skip)):
						# we have a list of pkgs to skip, and this catpkg is on the list, so skip:
						continue
				elif isinstance(self.skip, regextype):
					if self.select.match(catpkg):
						# regex skip match, continue
						continue
				dest_cat_set.add(cat)
				tcatdir = os.path.join(desttree.root,cat)
				tpkgdir = os.path.join(tcatdir,pkg)
				copied = False
				if self.replace == True or (isinstance(self.replace, list) and ((catpkg in self.replace) or (catall in self.replace))):
					if not os.path.exists(tcatdir):
						os.makedirs(tcatdir)
					if self.merge is True or (isinstance(self.merge, list) and ((catpkg in self.merge) or (catall in self.merge)) and os.path.isdir(tpkgdir)):
						# We are being told to merge, and the destination catpkg dir exists... so merging is required! :)
						# Manifests must be processed and combined:
						try:
							pkgdir_manifest_file = open("%s/Manifest" % pkgdir)
							pkgdir_manifest = pkgdir_manifest_file.readlines()
							pkgdir_manifest_file.close()
						except IOError:
							pkgdir_manifest = []
						try:
							tpkgdir_manifest_file = open("%s/Manifest" % tpkgdir)
							tpkgdir_manifest = tpkgdir_manifest_file.readlines()
							tpkgdir_manifest_file.close()
						except IOError:
							tpkgdir_manifest = []
						entries = {
							"AUX": {},
							"DIST": {},
							"EBUILD": {},
							"MISC": {}
						}
						for line in tpkgdir_manifest + pkgdir_manifest:
							if line.startswith(("AUX ", "DIST ", "EBUILD ", "MISC ")):
								entry_type = line.split(" ")[0]
								if entry_type in (("AUX", "DIST", "EBUILD", "MISC")):
									entries[entry_type][line.split(" ")[1]] = line
						runShell("cp -a %s %s" % (pkgdir, os.path.dirname(tpkgdir)))
						merged_manifest_file = open("%s/Manifest" % tpkgdir, "w")
						for entry_type in ("AUX", "DIST", "EBUILD", "MISC"):
							for key in sorted(entries[entry_type]):
								merged_manifest_file.write(entries[entry_type][key])
						merged_manifest_file.close()
					else:
						runShell("rm -rf %s; cp -a %s %s" % (tpkgdir, pkgdir, tpkgdir ))
					copied = True
				else:
					if not os.path.exists(tpkgdir):
						copied = True
					if not os.path.exists(tcatdir):
						os.makedirs(tcatdir)
					runShell("[ ! -e %s ] && cp -a %s %s || echo \"# skipping %s/%s\"" % (tpkgdir, pkgdir, tpkgdir, cat, pkg ))
				if copied:
					# log XML here.
					cpv = "/".join(tpkgdir.split("/")[-2:])
					mergeLog.write("%s\n" % cpv)
				# Record source tree of each copied catpkg to XML for later importing...
					if desttree.xml_out != None:
						catxml = desttree.xml_out.find("packages/category[@name='%s']" % cat)
						if catxml == None:
							catxml = etree.Element("category", name=cat)
							desttree.xml_out.append(catxml)
						pkgxml = desttree.xml_out.find("packages/category[@name='%s']/package/[@name='%s']" % ( cat ,pkg ))
						#remove existing
						if pkgxml != None:
							pkgxml.getparent().remove(pkgxml)
						pkgxml = etree.Element("package", name=pkg, repository=self.srctree.name)
						doMeta = True
						try:
							tpkgmeta = open("%s/metadata.xml" % tpkgdir, 'rb')
							try:
								metatree=etree.parse(tpkgmeta)
							except UnicodeDecodeError:
								doMeta = false
							tpkgmeta.close()
							if doMeta:
								use_vars = []
								usexml = etree.Element("use")
								for el in metatree.iterfind('.//flag'):
									name = el.get("name")
									if name != None:
										flag = etree.Element("flag")
										flag.attrib["name"] = name
										flag.text = etree.tostring(el, method="text").strip()
										usexml.append(flag)
								pkgxml.attrib["use"] = ",".join(use_vars)
								pkgxml.append(usexml)
						except IOError:
							pass
						catxml.append(pkgxml)

		if os.path.isdir(os.path.dirname(dest_cat_path)):
			# only write out if profiles/ dir exists -- it doesn't with shards.
			with open(dest_cat_path, "w") as f:
				f.write("\n".join(sorted(dest_cat_set)))

class ProfileDepFix(MergeStep):

	"ProfileDepFix undeprecates profiles marked as deprecated."

	def run(self,tree):
		fpath = os.path.join(tree.root,"profiles/profiles.desc")
		if os.path.exists(fpath):
			a = open(fpath,"r")
			for line in a:
				if line[0:1] == "#":
					continue
				sp = line.split()
				if len(sp) >= 2:
					prof_path = sp[1]
					runShell("rm -f %s/profiles/%s/deprecated" % ( tree.root, prof_path ))

class RunSed(MergeStep):

	"""
	Run sed commands on specified files.

	files: List of files.

	commands: List of commands.
	"""

	def __init__(self, files, commands):
		self.files = files
		self.commands = commands

	def run(self, tree):
		commands = list(itertools.chain.from_iterable(("-e", command) for command in self.commands))
		files = [os.path.join(tree.root, file) for file in self.files]
		run_command(["sed"] + commands + ["-i"] + files)

class GenCache(MergeStep):

	def __init__(self,cache_dir=None):
		self.cache_dir = cache_dir

	"GenCache runs egencache --update to update metadata."

	def run(self,tree):
		cmd = ["egencache", "--update", "--repo", tree.reponame if tree.reponame else tree.name, "--repositories-configuration", "[%s]\nlocation = %s" % (tree.reponame if tree.reponame else tree.name, tree.root), "--jobs", "36"]
		if self.cache_dir:
			cmd += [ "--cache-dir", self.cache_dir ]
		run_command(cmd, abort_on_failure=False)

class GenUseLocalDesc(MergeStep):

	"GenUseLocalDesc runs egencache to update use.local.desc"

	def run(self,tree):
		run_command(["egencache", "--update-use-local-desc", "--repo", tree.reponame if tree.reponame else tree.name, "--repositories-configuration", "[%s]\nlocation = %s" % (tree.reponame if tree.reponame else tree.name, tree.root)], abort_on_failure=False)

class GitCheckout(MergeStep):

	def __init__(self,branch):
		self.branch = branch

	def run(self,tree):
		runShell("( cd %s; git checkout %s )" % ( tree.root, self.branch ))

class CreateBranch(MergeStep):

	def __init__(self,branch):
		self.branch = branch

	def run(self,tree):
		runShell("( cd %s; git checkout -b %s --track origin/%s )" % ( tree.root, self.branch, self.branch ))


class Minify(MergeStep):

	"Minify removes ChangeLogs and shrinks Manifests."

	def run(self,tree):
		runShell("( cd %s; find -iname ChangeLog -exec rm -f {} \; )" % tree.root )
		runShell("( cd %s; find -iname Manifest -exec sed -n -i -e \"/DIST/p\" {} \; )" % tree.root )

# vim: ts=4 sw=4 noet
