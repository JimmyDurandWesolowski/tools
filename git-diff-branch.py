#! /usr/bin/env python

from argparse import ArgumentParser
from collections import defaultdict
import logging
import re
import signal
import sys

import colorama
import editdistance
from git import Repo
from git.objects import Commit
from progress.bar import Bar


# Borrowed from PyEsr
def commit_change_id(obj):
    '''Retrieve the Change-Id from the given commit'''
    match = obj.CHANGE_ID_REGEX.search(obj.message.lower())
    if not match:
        return None
    return match.group(1)

def commit_short(obj):
    return f'{obj.hexsha[:12]} "{obj.summary}"'

Commit.CHANGE_ID_REGEX = re.compile(r'[ ]*change-id: (.[a-z0-9]+)',
                                    re.MULTILINE)
Commit.change_id = property(commit_change_id)
Commit.short = commit_short


class Result:
    CONFIDENCE_MIN = 0.7
    CONFIDENCE_MAX = 1.0
    POSITIVE = False
    WEIGHT_MAX = 1.0

    def __init__(self, commit1, commit2, confidence):
        self.commit_src = commit1
        self.commit_dest = commit2
        self.weight = 0
        self.confidence = confidence

    def __str__(self):
        return self.__class__.__name__

    @classmethod
    def merge(cls, results):
        logger = logging.getLogger(f'BranchDiff.{cls.__name__}')
        res_dict = defaultdict(list)
        for result in results:
            value = result.confidence * result.weight
            res_dict[value].append(result)
        logger.debug('Merging results')
        for value, val_res in res_dict.items():
            res_str = ' '.join([str(res) for res in val_res])
            logger.debug(f'  Result with {value}: {res_str}')
        ret = res_dict[max(res_dict.keys())][0]
        logger.debug(f'-> winning result: {ret}')
        return ret


class ResultMatch(Result):
    POSITIVE = True

    def __init__(self, compare_class, commit1, commit2, confidence):
        super().__init__(commit1, commit2, confidence)
        self.compare_class = compare_class
        self.weight = compare_class.WEIGHT


class ResultMatchFull(ResultMatch):
    def __init__(self, compare_class, commit):
        super().__init__(compare_class, commit, commit,
                         Result.CONFIDENCE_MAX)


class ResultMatchPartial(ResultMatch):
    def __str__(self):
        return f'{self.__class__.__name__} ({self.confidence})'


class ResultFail(Result):
    def __init__(self, commit1, commit2):
        super().__init__(commit1, commit2, 0)


class CommitCompare:
    THRESHOLD = None
    WEIGHT = 0

    def __init__(self, logger=None):
        self.logger = logger
        if self.logger is None:
            self.logger = logging.getLogger(
                f'BranchDiff.{CommitCompare.__name__}')

    @classmethod
    def logcall(cls, func):
        def wrapped_call(self, commit1, commit2):
            ret = func(self, commit1, commit2)
            self.logger.info(f'{self.__class__.__name__}: {ret}')
            return ret
        return wrapped_call

    def __call__(self, commit1, commit2):
        raise NotImplementedError


class CommitCompareSubject(CommitCompare):
    THRESHOLD = 0.7
    WEIGHT = 0.4

    @CommitCompare.logcall
    def __call__(self, commit1, commit2):
        distance = editdistance.eval(commit1.summary, commit2.summary)
        if distance == 0:
            self.logger.debug(
                f'no distance between {commit1.summary} and {commit2.summary}')
            return ResultMatchPartial(self, commit1, commit2,
                                      Result.CONFIDENCE_MAX)
        distance /= max(len(commit1.summary), len(commit2.summary))
        distance = Result.CONFIDENCE_MAX - distance
        self.logger.debug(
            f'distance "{commit1.summary}" / "{commit2.summary}": {distance}')
        if distance >= self.THRESHOLD:
            return ResultMatchPartial(self, commit1, commit2, distance)
        return ResultFail(commit1, commit2)


class CommitCompareSafe(CommitCompare):
    WEIGHT = Result.WEIGHT_MAX


class CommitCompareHash(CommitCompareSafe):
    @CommitCompare.logcall
    def __call__(self, commit1, commit2):
        ret = commit1.hexsha == commit2.hexsha
        self.logger.debug(f'{commit1.hexsha} == {commit2.hexsha}: {ret}')
        if ret:
            return ResultMatchFull(self, commit1)
        return ResultFail(commit1, commit2)


class CommitCompareChangeId(CommitCompareSafe):
    @CommitCompare.logcall
    def __call__(self, commit1, commit2):
        ret = (commit1.change_id and commit2.change_id and
               commit1.change_id == commit2.change_id)
        self.logger.debug(f'{commit1.change_id} == {commit2.change_id}: {ret}')
        if ret:
            return ResultMatchPartial(self, commit1, commit2,
                                      Result.CONFIDENCE_MAX)
        return ResultFail(commit1, commit2)


class BranchDiff:
    def __init__(self, rev_range1, rev_range2, repository_path='.',
                 loglevel=logging.WARN):
        self.repo = Repo(repository_path)
        self.rev_range1 = rev_range1
        self.rev_range2 = rev_range2
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.addHandler(handler)
        self.logger.setLevel(loglevel)
        self.results = []
        self.compare_obj = [
            CommitCompareHash(),
            CommitCompareChangeId(),
            CommitCompareSubject()
        ]

    def _compare(self):
        def signal_handler(signal, frame):
            bar.finish()
            sys.exit(0)
        self.results = []
        commits1 = list(self.repo.iter_commits(self.rev_range1))
        commits2 = list(self.repo.iter_commits(self.rev_range2))
        checked = []
        bar = Bar('Comparing', max=len(commits1))
        signal.signal(signal.SIGINT, signal_handler)
        for commit1 in commits1:
            self.logger.info(f'Checking {commit1}')
            commit1_res = []
            for commit2 in commits2:
                self.logger.info(f'  against {commit2}')
                result = self.compare_commits(commit1, commit2)
                commit1_res.append(result)
                self.logger.info(f'    {result}')
                if result.POSITIVE:
                    checked.append(commit2)
            result = Result.merge(commit1_res)
            self.logger.info(f'    -> {result}')
            self.results.append(result)
            bar.next()
        bar.finish()
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        for commit in [comt for comt in commits2 if comt not in checked]:
            self.logger.info(f'{commit.short()} not previously seen')
            self.results.append(ResultFail(None, commit))

    def compare_commits(self, commit1, commit2):
        results = []
        for func in self.compare_obj:
            result = func(commit1, commit2)
            results.append(result)
            if result.confidence == Result.CONFIDENCE_MAX:
                self.logger.info(
                    f'Found maximum confidence result, skipping other tests')
                break
        return Result.merge(results)

    def compare(self):
        def result_print_filter(msg, filter_cond, show_func):
            results_filtered = [result for result in self.results
                                if filter_cond(result)]
            if not results_filtered:
                return
            print(msg)
            for result in results_filtered:
                show_func(result)
            print('')

        if not self.results:
            self._compare()
        result_print_filter(
            f'Commits in {self.rev_range1} and {self.rev_range2}:',
            lambda result: isinstance(result, ResultMatchFull),
            lambda result: print(f'- {result.commit_src.short()}'))

        result_print_filter(
            f'Commits matching between {self.rev_range1} and '
            f'{self.rev_range2}:',
            lambda result: isinstance(result, ResultMatchPartial),
            lambda result: print(
                f'- {result.commit_src.short()} and '
                f'{result.commit_dest.short()} ({result.confidence})'))

        result_print_filter(
            f'Commits only in {self.rev_range1}:',
            lambda result: isinstance(result, ResultFail) and
            result.commit_src is not None,
            lambda result: print(f'- {result.commit_src.short()}'))

        result_print_filter(
            f'Commits only in {self.rev_range2}:',
            lambda result: isinstance(result, ResultFail) and
            result.commit_src is None,
            lambda result: print(f'- {result.commit_dest.short()}'))


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('rev_range1')
    parser.add_argument('rev_range2')
    parser.add_argument('-v', '--verbose', action='count',
                        help='increase the verbosity (can be repeated twice)')
    args = parser.parse_args()
    loglevel = logging.WARN
    if args.verbose:
        loglevel = logging.INFO
        if args.verbose == 2:
            loglevel = logging.DEBUG
    diff = BranchDiff(args.rev_range1, args.rev_range2, loglevel=loglevel)
    diff.compare()
