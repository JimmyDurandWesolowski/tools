#! /bin/bash


if [ $# -ne 2 ]; then
    echo "Usage:"
    echo "  $0 <cmit-start1>..<cmit-end1> <cmit-start2>..<cmit-end2>"
    exit 1
fi

OUTDIR=test-diff_output
COMMON_DIR=${OUTDIR}/common
ADDITIONAL_DIR=${OUTDIR}/additional
MISSING_DIR=${OUTDIR}/missing
COMMITS_LIST1=$1
COMMITS_LIST2=$2
PROCFILE1=${OUTDIR}/list1.txt
PROCFILE2=${OUTDIR}/list2.txt

rm -rf ${OUTDIR}
mkdir -p ${COMMON_DIR} ${ADDITIONAL_DIR} ${MISSING_DIR}
touch ${PROCFILE1} ${PROCFILE2}

LOG1=$(git log --graph --pretty=format:'%at|1|%h|%f' ${COMMITS_LIST1} | \
	      cut -c 2-)
LOG2=$(git log --graph --pretty=format:'%at|2|%h|%f' ${COMMITS_LIST2} | \
	      cut -c 2-)
LOGS=$(echo "${LOG1}" "${LOG2}" | sort -n)
echo "${LOGS}" > ${OUTDIR}/logs.txt
NB=1

for log in ${LOGS}; do
    NB=$(printf "%03d" $NB)
    date=$(echo ${log} | cut -d '|' -f 1)
    id=$(echo ${log} | cut -d '|' -f 2)
    hash=$(echo ${log} | cut -d '|' -f 3)
    subject=$(echo ${log} | cut -d '|' -f 4)

    # Check if this is a commit from commit list 1
    if [ $id = "1" ]; then
	# Check if this commit from list 1 is in list 2
	common=$(echo "${LOG2}" | grep "${subject}")

	if [ -n "${common}" ]; then
	    echo ${common}
	    # There is a common patch, get the diff
	    hash2=$(echo ${common} | cut -d '|' -f 3)
	    subject2=$(echo ${common} | cut -d '|' -f 4)
	    diff <(git show --format=%gs ${hash}) \
		 <(git show --format=%gs ${hash2}) \
		 > ${COMMON_DIR}/${NB}-${hash}-${hash2}-${subject}.patch
	    echo "${hash2} ${subject2}"
	    echo "${hash2} ${subject2}" >> ${PROCFILE2}
	else
	    # There is a new patch from list 1, get the patch
	    git format-patch ${hash}~..${hash} --stdout > \
		${MISSING_DIR}/${NB}-${hash}-${subject}.patch
	fi
	echo "${hash} - ${subject}" >> ${PROCFILE1}
    else
	set -x
	grep ${hash} ${PROCFILE2}
	set +x
	# Check that we did not process this log from commit list 2
	if [ -z "$(grep ${hash} ${PROCFILE2})" ]; then
	    # Not processed already. That is a new commit from list 2
	    git show ${hash} > \
		${ADDITIONAL_DIR}/${NB}-${hash}-${subject}.patch
	    echo "${hash} - ${subject}" >> ${PROCFILE2}
	fi
    fi


    # force decimal (base 10)
    NB=$(( 10#$NB + 1))
done
