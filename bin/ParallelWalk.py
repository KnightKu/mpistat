## Copyright Genome Research Ltd
# Author gmpc@sanger.ac.uk
# This program is released under the GNU Public License V2 or later (GPLV2+)
from __future__ import print_function
from mpi4py import MPI
import sys
import os
import random
import time
from collections import deque

class ParallelWalk():
    """This class implements a parallel directory walking algorithm described 
    by LaFon, Misra and Bringhurst
    http://conferences.computer.org/sc/2012/papers/1000a015.pdf

    The class expects an MPI communicator as an argument.
   
    from lib.parallelwalk import ParallelWalk
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    walker = ParallelWalk(comm)

    To start the walker, call the execute() method. MPI rank 0 should pass 
    in a seed directory. Currently seeds to MPI ranks other than rank 0 will 
    be ignored.
    
    if rank == 0:
       seed = "/my/dir"
    else:
       seed = None
    results = walker.execute(seed)

    As it stands, the walker will walk the directory tree and then exit. It will
    return no data and perform no actions on file and directories it encounters.

    The execute method should only be executed once; there is alot of undefined state
    left in the walker once it has finished crawling.

    In order to customize its behaviour you should subclass ParallelWalk() and extend
    the ProcessDir() and ProcessFile() methods. These methods are called on every
    directory and file the walker encounters.

    The amount of work the ProcessDir() and ProcessFile() methods carry out should be
    as small as possible to ensure efficient work balancing between the workers.
    Tasks stuck in these functions will not be able to answer work requests from other
    nodes.

    If you want to return summary data from the walker, use the results
    attribute. You can set results to a particular datatype by setting the results
    parameter when you instantiate the class. By default results is None.

    results are gathered and returned as a list by the rank 0
    walker. The list contains the results from each MPI rank. If you wish to change
    this behaviour you can extend the gatherResults() method.

    The following example modified the walker to print out the name of each
    file it encounters and count the total number of files.

    class printfiles(ParallelWalk):
        def ProcessFile(self, filename)
            print filename
            self.results += 1
         
    walker  = printfile(comm, results=0)
    listofresults = walker.Execute()


"""
    def __init__(self, comm, results=None):
        self.comm = comm.Dup()
        self.rank = self.comm.Get_rank()
        self.workers = self.comm.size
        self.others = range(0, self.rank) + range(self.rank+1, self.workers)
        self.nextworker = (self.rank + 1) % self.workers
        self.colour = "White"
        self.token = False
        self.first = True
        self.workrequest = False
        self.items = deque()
        self.results = results
        self.finished = False

    def ProcessItem(self):
        """
        Stub Method to be overriden in a subclass.
        Process an item from the work queue.
        """


    def _CheckforRequests(self):
        """Listen for incoming communication data from our peers and answer
        accordigly.
        """
        # tags
        # 0 = work request
        # 1 = work item
        # 2 = token
        # 3 = Shutdown message
        status = MPI.Status()
        while self.comm.Iprobe(source=MPI.ANY_SOURCE, tag=MPI.ANY_TAG):
            request = self.comm.recv(source=MPI.ANY_SOURCE, tag=MPI.ANY_TAG, 
                                status=status)
            source = status.source
            tag = status.tag

            if tag == 0:
                numitems = len(self.items)
                if numitems > 1:
                    split = random.randrange(1, numitems)
    #            or split list in half
    #                split = numitems / 2
                    senditems = list(self.items)[:split]
                    remainingitems = list(self.items)[split:]
                    self.items = deque(remainingitems)
                    self.comm.send(senditems, dest=source, tag=1)
                    if source < self.rank:
                        self.colour = "Black"
                else:
                    self.comm.send("NoWork", dest=source, tag=1)

            if tag == 1:
                self.mpirequest.wait()
                if request != "NoWork":
                    self.items.extendleft(request)
                self.workrequest = False

            if tag == 2:
                self.token = request

            if tag == 3:
                self.finished = True
        return()



    def _AskForWork(self):
        """Send a work request to a random peer."""
        target = random.choice(self.others)
        self.mpirequest = self.comm.isend("Hungry", dest=target, tag=0)
        self.workrequest = True

    def _CheckForTermination(self):
        """Dijkstra distributed termiation algorithm."""
        # single process case is special; we can terminate straight away.
        if self.workers == 1:
            self.finished = True
            return()
        # We are done when rank 0 is white and has a white token.
        if (self.rank == 0 and self.token == "White" and 
            self.colour == "White"):
            if self.first == True:
                self.first = False
            else:
                # Tell the other workers that they are done, and then quit.
                self._sendShutdown()            
                self.finished = True

        # If we have the token, set the process and token colours as then send
        # the token on to the next process.
        if self.token != False:
            if self.rank == 0:
                self.colour = "White"
                self.token = "White"
                self.comm.send(self.token, self.nextworker, tag=2)
                self.token = False
            else:
                if self.colour == "White":
                    self.comm.send(self.token, self.nextworker, tag=2)
                    self.token = False

                elif self.colour == "Black":
                    self.token = "Black"
                    self.colour = "White"
                    self.comm.send(self.token, self.nextworker, tag=2)
                    self.token = False

    def _sendShutdown(self):
        """
        Send shutdown signal to the other ranks.
        """
        for dest in range(1, self.workers):
            self.comm.send("Shutdown", dest=dest, tag=3)

    def gatherResults(self):
        """
        This method defines how summary data is handled. By default
        results are gathered to the rank 0 MPI process.
        """
        data = self.comm.gather(self.results, root=0)
        return(data)

    def _tidy(self):
        self.comm.Free()

    def Execute(self, seeds):
        """
        This method starts the walkers. Seeds are evenly distributed
        amongst the worker nodes. Assumption is that all seeds are valid
        directories which are openable by the user running the job.
        The rank 0 walker will return a list containing the results
        attributes for all of the walkers. This can be used to print out
        summary statistics etc.
        """

        # Evenly distribute seeds amongst workers
        for i in range(self.rank, len(seeds), self.workers):
            self.items.append(seeds[i])

        # Initialise termination detection
        if self.rank == 0:
            self.token = "White"
        else:
            self.token = False

        # main loop
        # See if we have any pending communication requests.
        # If we have work, then do it, otherwise we ask our peers for some.
        while self.finished == False:
            self._CheckforRequests ()
            if len(self.items) > 0:
                self.ProcessItem()
            else:
                # We only want one request in-flight, otherwise we
                # ping-pong worklist between nodes.
                if self.workrequest == False:
                    self._AskForWork()
            # If we have no more work, we might be finished
            if len(self.items) == 0:
                self._CheckForTermination()
        # Gather the summary data from other ranks and then exit.
        data = self.gatherResults()
        self._tidy()
        return(data)
