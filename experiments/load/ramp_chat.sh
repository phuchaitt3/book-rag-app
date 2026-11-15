#!/usr/bin/env bash
# Chat+reads ramp with the stop rule from docs/benchmarks/load-test.md: one step past the first break.
cd "$(dirname "$0")"; broke=0
for n in 5 10 20 40 80 160 320; do
  ./run_step.sh chat $n > /dev/null 2>&1
  rc=$(grep -o 'k6 exit=[0-9]*' results/chat-$n.k6.txt | cut -d= -f2)
  echo "step $n exit=$rc"
  [ "$broke" = 1 ] && break
  [ "$rc" != 0 ] && broke=1
done
