# A profile with the largest number of named exec transitions that
# apparmor_parser 5.x accepts in one profile block (12). The check must
# accept this file: it is the budget, not a violation.
#
# The children are nested profiles, so the transitions name local profiles
# the way the repository's container policies do.
profile fixture-limit /usr/bin/fixture-limit {
  /usr/bin/fixture-child00 px -> fixture-child00,
  /usr/bin/fixture-child01 px -> fixture-child01,
  /usr/bin/fixture-child02 px -> fixture-child02,
  /usr/bin/fixture-child03 px -> fixture-child03,
  /usr/bin/fixture-child04 px -> fixture-child04,
  /usr/bin/fixture-child05 px -> fixture-child05,
  /usr/bin/fixture-child06 px -> fixture-child06,
  /usr/bin/fixture-child07 px -> fixture-child07,
  /usr/bin/fixture-child08 px -> fixture-child08,
  /usr/bin/fixture-child09 px -> fixture-child09,
  /usr/bin/fixture-child10 px -> fixture-child10,
  /usr/bin/fixture-child11 px -> fixture-child11,
  /usr/bin/fixture-limit r,

  profile fixture-child00 {
    /usr/bin/fixture-child00 r,
  }

  profile fixture-child01 {
    /usr/bin/fixture-child01 r,
  }

  profile fixture-child02 {
    /usr/bin/fixture-child02 r,
  }

  profile fixture-child03 {
    /usr/bin/fixture-child03 r,
  }

  profile fixture-child04 {
    /usr/bin/fixture-child04 r,
  }

  profile fixture-child05 {
    /usr/bin/fixture-child05 r,
  }

  profile fixture-child06 {
    /usr/bin/fixture-child06 r,
  }

  profile fixture-child07 {
    /usr/bin/fixture-child07 r,
  }

  profile fixture-child08 {
    /usr/bin/fixture-child08 r,
  }

  profile fixture-child09 {
    /usr/bin/fixture-child09 r,
  }

  profile fixture-child10 {
    /usr/bin/fixture-child10 r,
  }

  profile fixture-child11 {
    /usr/bin/fixture-child11 r,
  }
}
