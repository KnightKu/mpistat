#!/bin/bash

# gzip any MPI stat files for Lustretree that are kicking around
# Christopher Harrison <ch12@sanger.ac.uk>

set -eu -o pipefail

ME=$(readlink -f "$0")
DATADIR=/lustre/scratch114/teams/hgi/lustre_reports/mpistat/data

create_fofn() {
  # Create file of filenames and write length to stdout
  local fofn="$1"

  find $DATADIR -type f -name "*.dat" \
  | tee $fofn \
  | wc -l
}

gz_fofn_line() {
  # gzip file at specified line of fofn
  local fofn="$1"
  local linenum="$2"
  
  local togz=$(sed "${linenum}q;d" $fofn)
  echo "gzipping ${togz}..."
  gzip -9 $togz
}

main() {
  local fofn

  case "${1:-}" in
    "run")
      fofn="$2"
      local linenum="$3"

      gz_fofn_line "$fofn" "$linenum"
      ;;

    *)
      local id=$(date +%Y%m%d)
      local job_name="gz_fofn${id}"
      fofn="$DATADIR/${id}.togz"
      local count=$(create_fofn "$fofn")

      if [ "$count" -eq "0" ]; then
        echo "Nothing to do!"
        rm "$fofn"
        exit 0
      fi

      echo "Creating job array with $count elements"
      bsub -J "${job_name}[1-${count}]" "$ME run $fofn \$LSB_JOBINDEX"
      bsub -w "ended(${job_name})" "rm $fofn"
      ;;
  esac
}

main $@
