#!/usr/bin/env /usr/local/bin/python
from __future__ import print_function

import getopt
import logging
import os
import sys
import tarfile
import shutil

sys.path.append("/usr/local/lib")

import freenasOS.Configuration as Configuration
import freenasOS.Update as Update
import freenasOS.Exceptions as Exceptions
from freenasOS import log_to_handler
from freenasOS.Installer import ProgressHandler

class ProgressBar(object):
    def __init__(self):
        self.message = None
        self.percentage = 0
        self.write_stream = sys.stderr
        self.used_flag = False

    def __enter__(self):
        return self

    def draw(self):
        progress_width = 40
        filled_width = int(self.percentage * progress_width)
        self.write_stream.write('\033[2K\033[A\033[2K\r')
        self.write_stream.write('Status: {}\n'.format(self.message))
        self.write_stream.write(
            'Total Progress: [{}{}] {:.2%}'.format(
                '#' * filled_width,
                '_' * (progress_width - filled_width),
                self.percentage
            )
        )
        self.write_stream.flush()

    def update(self, percentage=None, message=None):
        if not self.used_flag:
            self.write_stream.write('\n')
            self.used_flag = True
        if percentage:
            self.percentage = float(percentage / 100.0)
        if message:
            self.message = message
        self.draw()

    def finish(self):
        self.percentage = 1

    def __exit__(self, type, value, traceback):
        if self.used_flag:
            self.draw()
            self.write_stream.write('\n')


class UpdateHandler(object):
    "A handler for Downloading and Applying Updates calls"

    def __init__(self, update_progress=None):
        self.progress = 0
        self.details = ''
        self.finished = False
        self.error = False
        self.indeterminate = False
        self.reboot = False
        self.pkgname = ''
        self.pkgversion = ''
        self.operation = ''
        self.filesize = 0
        self.numfilestotal = 0
        self.numfilesdone = 0
        self._baseprogress = 0
        self.master_progress = 0
        # Below is the function handle passed to this by the caller so that
        # its status and progress can be updated accordingly
        self.update_progress = update_progress

    def check_handler(self, index, pkg, pkgList):
        self.pkgname = pkg.Name()
        self.pkgversion = pkg.Version()
        self.operation = 'Downloading'
        self.details = 'Downloading {0}'.format(self.pkgname)
        stepprogress = int((1.0 / float(len(pkgList))) * 100)
        self._baseprogress = index * stepprogress
        self.progress = (index - 1) * stepprogress

    def get_handler(self, method, filename, size=None, progress=None, download_rate=None):
        if progress is not None:
            self.progress = (progress * self._baseprogress) / 100
            if self.progress == 0:
                self.progress = 1
            display_size = ' Size: {0}'.format(size) if size else ''
            display_rate = ' Rate: {0} B/s'.format(download_rate) if download_rate else ''
            self.details = 'Downloading: {0} Progress:{1}{2}{3}'.format(
                self.pkgname, progress, display_size, display_rate
            )
        self.increment_progress()

    def install_handler(self, index, name, packages):
        self.indeterminate = False
        total = len(packages)
        self.numfilesdone = index
        self.numfilesdone = total
        self.progress = int((float(index) / float(total)) * 100.0)
        self.operation = 'Installing'
        self.details = 'Installing {0}'.format(name)
        self.increment_progress()

    def increment_progress(self):
        # Doing the drill below as there is a small window when
        # step*progress logic does not catch up with the new value of step
        if self.progress >= self.master_progress:
            self.master_progress = self.progress
        if self.update_progress is not None:
            self.update_progress(self.master_progress, self.details)


def ExtractFrozenUpdate(tarball, dest_dir, verbose=False):
    """
    Extract the files in the given tarball into dest_dir.
    This assumes dest_dir already exists.
    """
    with tarfile.open(tarball) as tf:
        files = tf.getmembers()
        for f in files:
            if f.name in ("./", ".", "./."):
                continue
            if not f.name.startswith("./"):
                if verbose:
                    print("Illegal member {0}".format(f), file=sys.stderr)
                continue
            if len(f.name.split("/")) != 2:
                if verbose:
                    print("Illegal member name {0} has too many path components".format(f.name), file=sys.stderr)
                continue
            if verbose:
                print("Extracting {0}".format(f.name), file=sys.stderr)
            tf.extract(f.name, path=dest_dir)
            if verbose:
                print("Done extracting {0}".format(f.name), file=sys.stderr)
    return True


def PrintDifferences(diffs):
    for type in diffs:
        if type == "Packages":
            pkg_diffs = diffs[type]
            for (pkg, op, old) in pkg_diffs:
                if op == "delete":
                    print("Delete package {0}".format(pkg.Name()), file=sys.stderr)
                elif op == "install":
                    print("Install package {0}-{1}".format(pkg.Name(), pkg.Version()), file=sys.stderr)
                elif op == "upgrade":
                    print("Upgrade package {0} {1}->{2}".format(pkg.Name(), old.Version(), pkg.Version()), file=sys.stderr)
                else:
                    print("Unknown package operation {0} for packge {1}-{2}".format(op, pkg.Name(), pkg.Version()), file=sys.stderr)
        elif type == "Restart":
            for svc in diffs[type]:
                desc = Update.GetServiceDescription(svc)
                if desc:
                    print(str(desc), file=sys.stderr)
                else:
                    print("Unknown service restart {0}?!".format(svc), file=sys.stderr)
        elif type in ("Train", "Sequence"):
            # Train and Sequence are a single tuple, (old, new)
            old, new = diffs[type]
            print("{0} {1} -> {2}".format(type, old, new), file=sys.stderr)
        elif type == "Reboot":
            rr = diffs[type]
            print("Reboot is (conditionally) {0}required".format("" if rr else "not "), file=sys.stderr)
        else:
            print("*** Unknown key {0} (value {1})".format(type, str(diffs[type])), file=sys.stderrr)


def DoDownload(train, cache_dir, pkg_type, verbose, ignore_space=False):

    try:
        if not verbose:
            with ProgressBar() as progress_bar:
                handler = UpdateHandler(progress_bar.update)
                rv = Update.DownloadUpdate(
                    train,
                    cache_dir,
                    get_handler=handler.get_handler,
                    check_handler=handler.check_handler,
                    pkg_type=pkg_type,
                )
                if rv is False:
                    progress_bar.update(message="No updates available")
        else:
            rv = Update.DownloadUpdate(train, cache_dir, pkg_type=pkg_type, ignore_space=ignore_space)
    except Exceptions.ManifestInvalidSignature:
        log.error("Manifest has invalid signature")
        print("Manifest has invalid signature", file=sys.stderr)
        sys.exit(1)
    except Exceptions.UpdateBusyCacheException as e:
        log.error(str(e))
        print("Download cache directory is busy", file=sys.stderr)
        sys.exit(1)
    except Exceptions.UpdateIncompleteCacheException:
        log.error(str(e))
        print("Incomplete download cache, cannot update", file=sys.stderr)
        sys.exit(1)
    except Exceptions.ChecksumFailException as e:
        log.error(str(e))
        print("Checksum error, cannot update", file=sys.stderr)
        sys.exit(1)
    except Exceptions.UpdateInvalidUpdateException as e:
        log.error(str(e))
        print("Update not permitted:\n{0}".format(e.value), file=sys.stderr)
        sys.exit(1)
    except Exceptions.UpdateInsufficientSpace as e:
        log.error(str(e), exc_info=True)
        print(e.value if e.value else "Insufficient space for download")
        sys.exit(1)
    except BaseException as e:
        log.error(str(e), exc_info=True)
        print("Received exception during download phase, cannot update", file=sys.stderr)
        sys.exit(1)

    return rv


def DoUpdate(cache_dir, verbose, ignore_space=False, force_trampoline=None):
    """
    Common code to apply an update once it's been downloaded.
    This will handle all of the exceptions in a common fashion.
    Raises an exception on error.
    """
    global log

    try:
        diffs = Update.PendingUpdatesChanges(cache_dir)
    except Exceptions.UpdateBusyCacheException:
        log.error("Cache directory busy, cannot update")
        raise
    except Exceptions.UpdateInvalidUpdateException as e:
        log.error("Unable not permitted: {0}".format(e.value))
        raise
    except BaseException as e:
        log.error("Unable to update: {0}".format(str(e)))
        raise
    if verbose:
        PrintDifferences(diffs)

    if not diffs:
        log.debug("No updates to apply")
        return False

    try:
        if not verbose:
            with ProgressBar() as progress_bar:
                handler = UpdateHandler(progress_bar.update)
                rv = Update.ApplyUpdate(
                    cache_dir,
                    install_handler=handler.install_handler,
                    ignore_space=ignore_space,
                    force_trampoline=force_trampoline,
                )
                if rv is False:
                    progress_bar.update(message="Updates were not applied")
        else:
            with ProgressHandler() as pf:
                  rv = Update.ApplyUpdate(cache_dir,
                                          progressFunc=pf.update,
                                          ignore_space=ignore_space,
                                          force_trampoline=force_trampoline,
                                          )
                  
    except Exceptions.UpdateInsufficientSpace as e:
        log.error(str(e))
        print(e.value if e.value else "Insufficient space for update")
        sys.exit(1)
    except BaseException as e:
        log.error("Unable to apply update: {0}".format(str(e)))
        raise
    if rv and verbose:
        print("System should be rebooted now", file=sys.stderr)

    return rv

def main():
    global log

    def usage():
        print("""Usage: {0} [-C cache_dir] [-d] [-T train] [--no-delta] [--reboot|-R] [--server|-S server][-B|--trampline yes|no] [--force|-F] [-v] <cmd>
or	{0} <update_tar_file>
where cmd is one of:
        check\tCheck for updates
        update\tDo an update""".format(sys.argv[0]), file=sys.stderr)
        sys.exit(1)

    try:
        short_opts = "B:C:dFRS:T:v"
        long_opts = [
            "cache=",
            "debug",
            "reboot",
            "train=",
            "verbose",
            "no-delta",
            "force",
            "server=",
            "trampoline=",
            "snl"
        ]
        opts, args = getopt.getopt(sys.argv[1:], short_opts, long_opts)
    except getopt.GetoptError as err:
        print(str(err), file=sys.stderr)
        usage()

    do_reboot = False
    verbose = False
    debug = 0
    config = None
    # Should I get this from a configuration file somewhere?
    cache_dir = "/var/db/system/update"
    train = None
    pkg_type = None
    snl = False
    force = False
    server = None
    force_trampoline = None
    
    for o, a in opts:
        if o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-d", "--debug"):
            debug += 1
        elif o in ('-C', "--cache"):
            cache_dir = a
        elif o in ("-R", "--reboot"):
            do_reboot = True
        elif o in ("-S", "--server"):
            server = a
        elif o in ("-T", "--train"):
            train = a
        elif o in ("--no-delta"):
            pkg_type = Update.PkgFileFullOnly
        elif o in ("-B", "--trampoline"):
            if a in ("true", "True", "yes", "YES", "Yes"):
                force_trampoline = True
            elif a in ("false", "False", "no", "NO", "No"):
                force_trampoline = False
            else:
                print("Trampoline option must be boolean [yes/no]", file=sys.stderr)
                usage()
        elif o in ("--snl"):
            snl = True
        elif o in ("-F", "--force"):
            force = True
        else:
            assert False, "unhandled option {0}".format(o)

    if verbose:
        log_to_handler('stderr')
    log = logging.getLogger('freenas-update')

    config = Configuration.SystemConfiguration()
    if server:
        assert server in config.ListUpdateServers(), "Unknown update server {}".format(server)
        config.SetUpdateServer(server, save=False)
        
    if train is None:
        train = config.SystemManifest().Train()

    if len(args) != 1:
        usage()

    if args[0] == "check":
        # To see if we have an update available, we
        # call Update.DownloadUpdate.  If we have been
        # given a cache directory, we pass that in; otherwise,
        # we make a temporary directory and use that.  We
        # have to clean up afterwards in that case.

        rv = DoDownload(train, cache_dir, pkg_type, verbose, ignore_space=force)
        if rv is False:
            if verbose:
                print("No updates available")
            Update.RemoveUpdate(cache_dir)
            sys.exit(1)
        else:
            diffs = Update.PendingUpdatesChanges(cache_dir)
            if diffs is None or len(diffs) == 0:
                print("Strangely, DownloadUpdate says there updates, but PendingUpdates says otherwise", file=sys.stderr)
                sys.exit(1)
            PrintDifferences(diffs)
            if snl:
                print("I've got a fever, and the only prescription is applying the pending update.")
            sys.exit(0)

    elif args[0] == "update":
        # This will attempt to apply an update.
        # If cache_dir is given, then we will only check that directory,
        # not force a download if it is already there.  If cache_dir is not
        # given, however, then it downloads.  (The reason is that you would
        # want to run "freenas-update -c /foo check" to look for an update,
        # and it will download the latest one as necessary, and then run
        # "freenas-update -c /foo update" if it said there was an update.

        # See if the cache directory has an update downloaded already
        do_download = True
        try:
            f = Update.VerifyUpdate(cache_dir)
            if f:
                f.close()
                do_download = False
        except Exceptions.UpdateBusyCacheException:
            print("Cache directory busy, cannot update", file=sys.stderr)
            sys.exit(0)
        except (Exceptions.UpdateInvalidCacheException, Exceptions.UpdateIncompleteCacheException):
            pass
        except:
            raise

        if do_download:
            rv = DoDownload(train, cache_dir, pkg_type, verbose, ignore_space=force)
            if rv is False:
                if verbose:
                    print("No updates available")
                Update.RemoveUpdate(cache_dir)
                sys.exit(1)

        try:
            rv = DoUpdate(cache_dir, verbose, ignore_space=force, force_trampoline=force_trampoline)
        except:
            sys.exit(1)
        else:
            if rv:
                if do_reboot:
                    os.system("/sbin/shutdown -r now")
                sys.exit(0)
            else:
                sys.exit(1)
    else:
        # If it's not a tarfile (possibly because it doesn't exist),
        # print usage and exit.
        try:
            if len(args) > 1:
                usage()
            if not tarfile.is_tarfile(args[0]):
                usage()
        except:
            usage()

        # Frozen tarball.  We'll extract it into the cache directory, and
        # then add a couple of things to make it pass sanity, and then apply it.
        # For now we just copy the code above.
        # First, remove the cache directory
        # Hrm, could overstep a locked file.
        shutil.rmtree(cache_dir, ignore_errors=True)
        try:
            os.makedirs(cache_dir)
        except BaseException as e:
            print("Unable to create cache directory {0}: {1}".format(cache_dir, str(e)))
            sys.exit(1)

        try:
            ExtractFrozenUpdate(args[0], cache_dir, verbose=verbose)
        except BaseException as e:
            print("Unable to extract frozen update {0}: {1}".format(args[0], str(e)))
            sys.exit(1)
        # Exciting!  Now we need to have a SEQUENCE file, or it will fail verification.
        with open(os.path.join(cache_dir, "SEQUENCE"), "w") as s:
            s.write(config.SystemManifest().Sequence())
        # And now the SERVER file
        with open(os.path.join(cache_dir, "SERVER"), "w") as s:
            s.write(config.UpdateServerName())

        try:
            rv = DoUpdate(cache_dir, verbose, ignore_space=force, force_trampoline=force_trampoline)
        except:
            sys.exit(1)
        else:
            if rv:
                if do_reboot:
                    os.system("/sbin/shutdown -r now")
                sys.exit(0)
            else:
                sys.exit(1)

if __name__ == "__main__":
    sys.exit(main())
