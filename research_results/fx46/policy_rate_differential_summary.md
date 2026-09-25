# FX-46: Historical Policy-Rate Differential Research

Generated: 2026-09-25T14:18:35+00:00
Git commit: 79a2e1e480ce681ff5f4966db6df400d5bf46c25 (clean)
Config hash: 88d2054d7df82607684dc1da8afa53ea65c9324481baf0336200a58843e76569
Macro data fingerprint: 1d488d1b91acd06b34516410b3881ef23e09b6b245de692c6dc34c6a47075dde (258 vintages, max released_at 2026-09-16T18:00:00+00:00)

Research experiment only -- no thresholds, scoring, signal, execution logic, or tradability claim. Returns are mid_open-to-mid_open RESEARCH returns, not executable P&L. A positive result below is evidence of statistical association at the tested horizon, era, and pair -- never proof of a durable, tradeable edge, and CI crossing zero does not prove the feature useless (see Limitations).

## EUR_USD

### ANNOUNCED / LEVEL

Total attempted observations: 1134

| Disposition | Count |
|---|---|
| BLOCKED | 651 |
| USABLE | 483 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 651 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| POSITIVE | 1d | 8 | 0.0003935607861479393184511870625 | -0.00165508740862337987558742475 | 0.007302673292711776912569298077 | 0.375 | 0 |
| POSITIVE | 5d | 8 | -0.00987839938767532197159643425 | -0.00869059452399252950658107815 | 0.02436196247488176262352706639 | 0.25 | 0 |
| POSITIVE | 20d | 8 | -0.05014406472291336915306537132 | -0.04105569536876210755876929725 | 0.03623435689193122433714195341 | 0 | 0 |
| NEGATIVE | 1d | 475 | 0.00004694087181758193230139798189 | -0.00002573560950501844385347860 | 0.004487643117240574612100716808 | 0.4947368421052631578947368421 | 0 |
| NEGATIVE | 5d | 474 | 0.0006431862454632901018288632764 | 0.0000693438675131343800463240 | 0.009558075090777449203755369477 | 0.5105485232067510548523206751 | 1 |
| NEGATIVE | 20d | 471 | 0.002620097408437532506197416174 | 0.0007350824753680947636444150 | 0.01803120510561963190621317714 | 0.5159235668789808917197452229 | 4 |
| ZERO | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(POSITIVE) - mean(NEGATIVE)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 8 | 475 | 1 | 13 | 0.0003466199143303573861497890806 | n/a | n/a | NOT_ESTIMABLE: at least one group has fewer than 2 distinct calendar-year clusters in the full sample -- a cluster bootstrap cannot estimate between-year uncertainty from a single cluster, no matter how it is resampled |
| 5d | 8 | 474 | 1 | 13 | -0.01052158563313861207342529754 | n/a | n/a | NOT_ESTIMABLE: at least one group has fewer than 2 distinct calendar-year clusters in the full sample -- a cluster bootstrap cannot estimate between-year uncertainty from a single cluster, no matter how it is resampled |
| 20d | 8 | 471 | 1 | 13 | -0.05276416213135090165926278749 | n/a | n/a | NOT_ESTIMABLE: at least one group has fewer than 2 distinct calendar-year clusters in the full sample -- a cluster bootstrap cannot estimate between-year uncertainty from a single cluster, no matter how it is resampled |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| POSITIVE | 1d | 0.0003935607861479393184511870625 n=8 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 5d | -0.00987839938767532197159643425 n=8 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 20d | -0.05014406472291336915306537132 n=8 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 1d | 0.0002893916105853680670113342542 n=48 | 0.0002967432188509474971165556671 n=158 | -0.0001430457686735909067576051978 n=269 |
| NEGATIVE | 5d | 0.002305711274351835291316453129 n=48 | 0.0003505102894455402951914019930 n=158 | 0.0005179683337623733121024251313 n=268 |
| NEGATIVE | 20d | 0.009207437998890809705894757969 n=48 | 0.001598066387803029262468935263 n=158 | 0.002036280626997888004022425906 n=265 |
| ZERO | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

### ANNOUNCED / CHANGE

Total attempted observations: 5700

| Disposition | Count |
|---|---|
| BLOCKED | 3304 |
| GAP | 4 |
| NO_ENTRY_AVAILABLE | 1 |
| USABLE | 2391 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 3304 |
| GAP | transition_unknown_due_to_gap | 4 |
| NO_ENTRY_AVAILABLE | no D-bar available strictly after as_of | 1 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| INCREASED | 1d | 24 | -0.001433132877641565557090457754 | -0.00142586667354425113607555105 | 0.004607361835225840748859839569 | 0.375 | 0 |
| INCREASED | 5d | 23 | -0.002426820549187244580314609152 | -0.00157171760195932275583005000 | 0.009291306115358903035326134648 | 0.3913043478260869565217391304 | 1 |
| INCREASED | 20d | 23 | 0.002018486751155841085359227930 | 0.0025027448064803368115290520 | 0.01941910616806913698513832427 | 0.5217391304347826086956521739 | 1 |
| DECREASED | 1d | 23 | 0.0008857749485671433817918572391 | 0.0009352753159959320063925610 | 0.005999251939821802020702038322 | 0.5652173913043478260869565217 | 1 |
| DECREASED | 5d | 23 | 0.001997875658366725273133361152 | 0.0005472545316712345972520650 | 0.01191508635937493385634602764 | 0.5652173913043478260869565217 | 1 |
| DECREASED | 20d | 23 | 0.004270442841996203911996004374 | 0.0037965936344051054835169300 | 0.02622437045873297561910556758 | 0.5652173913043478260869565217 | 1 |
| UNCHANGED | 1d | 2343 | 0.0001106120708828702944286924230 | 0.0 | 0.004584202511442128540542071900 | 0.4989329918907383696116090482 | 0 |
| UNCHANGED | 5d | 2340 | 0.0005244790455405108231795116295 | 0.0002599554978690815531526245 | 0.01012677699155547055716062921 | 0.5089743589743589743589743590 | 3 |
| UNCHANGED | 20d | 2325 | 0.001682229117434366021986195425 | 0.0008252046193519452853458910 | 0.01963373181403205362335638291 | 0.5178494623655913978494623656 | 18 |

**Primary contrast: mean(INCREASED) - mean(DECREASED)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 24 | 23 | 7 | 7 | -0.002318907826208708938882314993 | [-0.005518230662174711447360602873, 0.0003704916673827873388188162809] | 0.9474 |  |
| 5d | 23 | 23 | 7 | 7 | -0.004424696207553969853447970304 | [-0.01049540707411322882595745750, -0.0001253362242349212293933878424] | 0.9778 |  |
| 20d | 23 | 23 | 7 | 7 | -0.002251956090840362826636776444 | [-0.01392182637770653676003181791, 0.007652803097129696595437219548] | 0.6986 |  |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| INCREASED | 1d | -0.00302389925276873794421444554 n=5 (sparse) | n/a n=0 (sparse) | -0.001014510147344941244689408337 n=19 |
| INCREASED | 5d | 0.00199831418451153177051999598 n=5 (sparse) | n/a n=0 (sparse) | -0.003656024641881349122213110578 n=18 |
| INCREASED | 20d | 0.015655303429330276314140526 n=5 (sparse) | n/a n=0 (sparse) | -0.001769517881670390922635577089 n=18 |
| DECREASED | 1d | n/a n=0 (sparse) | -0.0003881965949446038533843238778 n=9 (sparse) | 0.001704756655110409461547973671 n=14 |
| DECREASED | 5d | n/a n=0 (sparse) | 0.001669167647784043154959050367 n=9 (sparse) | 0.002209187950884163777673989514 n=14 |
| DECREASED | 20d | n/a n=0 (sparse) | 0.008441223712600740884930378456 n=9 (sparse) | 0.001589226568036144429395335321 n=14 |
| UNCHANGED | 1d | 0.0001800013898974691347637734626 n=270 | 0.00007294282766633692272565207552 n=776 | 0.0001187047590880269710293766378 n=1297 |
| UNCHANGED | 5d | 0.0005279433637804716565623162152 n=270 | 0.0003162148904031694197942364276 n=776 | 0.0006486503117397283687850883868 n=1294 |
| UNCHANGED | 20d | 0.0002241102990186877047987039556 n=270 | 0.001282140918275543885745246236 n=776 | 0.002232784647942168307649681949 n=1279 |

### EFFECTIVE / LEVEL

Total attempted observations: 1134

| Disposition | Count |
|---|---|
| BLOCKED | 307 |
| UNAVAILABLE | 400 |
| USABLE | 427 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 307 |
| UNAVAILABLE | no_effective_state_established | 400 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| POSITIVE | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| POSITIVE | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| POSITIVE | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 1d | 427 | 0.00001968645621839285861035128150 | -0.00005159692482328053248026420 | 0.004544153134629431781564396453 | 0.4894613583138173302107728337 | 0 |
| NEGATIVE | 5d | 426 | 0.0004558594816448624748443461174 | -0.00017046931125200693482757270 | 0.009651851809789122216889966390 | 0.4929577464788732394366197183 | 1 |
| NEGATIVE | 20d | 423 | 0.001872597766967657079281405757 | -0.00021112635912593687321862130 | 0.01788274728312423718292145473 | 0.4964539007092198581560283688 | 4 |
| ZERO | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(POSITIVE) - mean(NEGATIVE)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 0 | 427 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 5d | 0 | 426 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 20d | 0 | 423 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| POSITIVE | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 1d | n/a n=0 (sparse) | 0.0002967432188509474971165556671 n=158 | -0.0001430457686735909067576051978 n=269 |
| NEGATIVE | 5d | n/a n=0 (sparse) | 0.0003505102894455402951914019930 n=158 | 0.0005179683337623733121024251313 n=268 |
| NEGATIVE | 20d | n/a n=0 (sparse) | 0.001598066387803029262468935263 n=158 | 0.002036280626997888004022425906 n=265 |
| ZERO | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

### EFFECTIVE / CHANGE

Total attempted observations: 5700

| Disposition | Count |
|---|---|
| BLOCKED | 1523 |
| GAP | 2 |
| NO_ENTRY_AVAILABLE | 1 |
| UNAVAILABLE | 2059 |
| USABLE | 2115 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 1523 |
| GAP | transition_unknown_due_to_gap | 2 |
| NO_ENTRY_AVAILABLE | no D-bar available strictly after as_of | 1 |
| UNAVAILABLE | no_effective_state_established | 2059 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| INCREASED | 1d | 18 | 0.0002258665005146387428826710889 | -0.00153521796148204367507369085 | 0.005867946508425698741335522096 | 0.3888888888888888888888888889 | 1 |
| INCREASED | 5d | 18 | -0.00001020035527701254818367197778 | -0.00287310645041994104884192905 | 0.01345840726773868672122756119 | 0.3333333333333333333333333333 | 1 |
| INCREASED | 20d | 18 | 0.001817395756502658383755092611 | -0.00657751140656430543924998145 | 0.02317954139312668453160913683 | 0.3333333333333333333333333333 | 1 |
| DECREASED | 1d | 23 | -0.0002705097317924791363097708217 | -0.00175994048861028204407108710 | 0.004774123943595025255864244906 | 0.4347826086956521739130434783 | 0 |
| DECREASED | 5d | 23 | 0.0018470966722018374779650277 | 0.0011958936505661459079833740 | 0.01162314108961233053480556370 | 0.5652173913043478260869565217 | 0 |
| DECREASED | 20d | 23 | 0.005538055611640295604685473083 | 0.0046600030873726458783575180 | 0.02540427705398197952062038301 | 0.5217391304347826086956521739 | 0 |
| UNCHANGED | 1d | 2073 | 0.0001004975971101295409422306792 | 0.0 | 0.004482849561933297085075867733 | 0.4983116256632899179932465027 | 0 |
| UNCHANGED | 5d | 2069 | 0.0004891941580275965680976275655 | -0.00003751008083422419775314620 | 0.009599829346232530502772471178 | 0.4978250362493958434026099565 | 4 |
| UNCHANGED | 20d | 2054 | 0.001826848894906258730624419146 | 0.0003669438517927101003174280 | 0.01779839634872202382286398307 | 0.5087633885102239532619279455 | 19 |

**Primary contrast: mean(INCREASED) - mean(DECREASED)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 18 | 23 | 6 | 7 | 0.0004963762323071178791924419106 | [-0.002009468477412933658153961660, 0.004194500818405567521501801804] | 0.351 |  |
| 5d | 18 | 23 | 6 | 7 | -0.001857297027478850026148699678 | [-0.005883317199624372110741857714, 0.004584595514265414651687514007] | 0.8084 |  |
| 20d | 18 | 23 | 6 | 7 | -0.003720659855137637220930380472 | [-0.01452645152531986160004920262, 0.007543067348073636142991269962] | 0.7438 |  |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| INCREASED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | 0.0002258665005146387428826710889 n=18 |
| INCREASED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | -0.00001020035527701254818367197778 n=18 |
| INCREASED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | 0.001817395756502658383755092611 n=18 |
| DECREASED | 1d | n/a n=0 (sparse) | 0.000005865433053902333373015188889 n=9 (sparse) | -0.0004481794806222957953915618286 n=14 |
| DECREASED | 5d | n/a n=0 (sparse) | 0.001373307760483113537656894267 n=9 (sparse) | 0.002151675258306731439591684907 n=14 |
| DECREASED | 20d | n/a n=0 (sparse) | 0.006667631646652054748206631167 n=9 (sparse) | 0.004811899589132736155279014314 n=14 |
| UNCHANGED | 1d | n/a n=0 (sparse) | 0.00006138274862024137338319487871 n=775 | 0.0001238519943209641556250139894 n=1298 |
| UNCHANGED | 5d | n/a n=0 (sparse) | 0.0003065920890718487687554383299 n=775 | 0.0005985578392027932794501752253 n=1294 |
| UNCHANGED | 20d | n/a n=0 (sparse) | 0.001298448946066953985672280178 n=775 | 0.002147028691896455116346004421 n=1279 |

## GBP_USD

### ANNOUNCED / LEVEL

Total attempted observations: 1134

| Disposition | Count |
|---|---|
| BLOCKED | 538 |
| USABLE | 596 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 538 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| POSITIVE | 1d | 215 | -0.0002583667636109805561868416228 | -0.00049948663873241390792796290 | 0.005271867007247173072194890422 | 0.4465116279069767441860465116 | 0 |
| POSITIVE | 5d | 214 | -0.001324783505303946513582328935 | -0.00163043914505538757665025375 | 0.01361162301273302205564831421 | 0.4626168224299065420560747664 | 1 |
| POSITIVE | 20d | 211 | -0.004475948296754478689022753877 | -0.00122857396607359602119660140 | 0.02604908058864868595805998659 | 0.4928909952606635071090047393 | 4 |
| NEGATIVE | 1d | 356 | 0.0003023511361105166543396945143 | 0.0003574889685968450214702645 | 0.004872062355114157705052693055 | 0.5337078651685393258426966292 | 0 |
| NEGATIVE | 5d | 356 | 0.0007223178041113380773474749775 | -0.00037074307145220108349120475 | 0.01150178857870894289412880289 | 0.4915730337078651685393258427 | 0 |
| NEGATIVE | 20d | 356 | 0.002487811620608114205997663216 | 0.0021973675105315530136981535 | 0.02281690014160199122851665539 | 0.5308988764044943820224719101 | 0 |
| ZERO | 1d | 25 | 0.000369300895985335488148605408 | 0.0008256123291441152187872670 | 0.003022639491777594531706346851 | 0.56 | 0 |
| ZERO | 5d | 25 | 0.000767210784136187764395348152 | 0.0008876671534518798499556170 | 0.007947946985395566449725608710 | 0.52 | 0 |
| ZERO | 20d | 25 | 0.003445137456795789150672940452 | 0.0018039687312086590499098020 | 0.01327381437526054938933892544 | 0.6 | 0 |

**Primary contrast: mean(POSITIVE) - mean(NEGATIVE)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 215 | 356 | 9 | 11 | -0.0005607178997214972105265361371 | [-0.001698835412514209463442157883, 0.0001642761164383009262810268932] | 0.9192 |  |
| 5d | 214 | 356 | 9 | 11 | -0.002047101309415284590929803917 | [-0.004407514841232622768967452153, 0.0001648693653665801119265185329] | 0.9664 |  |
| 20d | 211 | 356 | 9 | 11 | -0.006963759917362592895020417134 | [-0.01698718037090652563285435962, 0.002079509695953215115147104724] | 0.9364 |  |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| POSITIVE | 1d | -0.00009548369467689234622262356796 n=103 | 0.0005297584142681337047078402697 n=33 | -0.0007999501429808774705645500038 n=79 |
| POSITIVE | 5d | -0.001596856943183958142303175208 n=103 | -0.003815395712301994428499619909 n=33 | 0.00008821350665216603706533472692 n=78 |
| POSITIVE | 20d | -0.006515882132070312110989458340 n=103 | -0.01350011491724976019339259738 n=33 | 0.002296194150097189739067584605 n=75 |
| NEGATIVE | 1d | -0.0005939086835184472875613066805 n=41 | 0.0005669493643968716494278719472 n=125 | 0.0003216767891052174292445306716 n=190 |
| NEGATIVE | 5d | 0.002537398824095610394488209049 n=41 | -0.0001486084261272435952757347944 n=125 | 0.0009036202091664304145850071974 n=190 |
| NEGATIVE | 20d | 0.01051926526630614513875894972 n=41 | 0.000050417155629899484498107348 n=125 | 0.002358257455601048795177830271 n=190 |
| ZERO | 1d | 0.000369300895985335488148605408 n=25 | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 5d | 0.000767210784136187764395348152 n=25 | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 20d | 0.003445137456795789150672940452 n=25 | n/a n=0 (sparse) | n/a n=0 (sparse) |

### ANNOUNCED / CHANGE

Total attempted observations: 5701

| Disposition | Count |
|---|---|
| BLOCKED | 2749 |
| GAP | 3 |
| NO_ENTRY_AVAILABLE | 1 |
| NO_PRIOR_DAY | 1 |
| USABLE | 2947 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 2749 |
| GAP | transition_unknown_due_to_gap | 3 |
| NO_ENTRY_AVAILABLE | no D-bar available strictly after as_of | 1 |
| NO_PRIOR_DAY | no_prior_day | 1 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| INCREASED | 1d | 25 | 0.000570257611500192810023522144 | -0.00033027522935779816513761470 | 0.005835478890673238000342052655 | 0.48 | 0 |
| INCREASED | 5d | 25 | -0.000941856705884961901529131624 | -0.00123903064535796185358984550 | 0.01368844234118804503144960784 | 0.4 | 0 |
| INCREASED | 20d | 25 | 0.004602682958913800027283393732 | 0.0034460354143878146871838740 | 0.02323891998533963996424529324 | 0.52 | 0 |
| DECREASED | 1d | 34 | -0.001649087866416644195393716515 | -0.00088439708391102824502163615 | 0.006376783855293210182415461537 | 0.4411764705882352941176470588 | 1 |
| DECREASED | 5d | 34 | -0.001694917367274098915338858868 | -0.00406301207836944874495851535 | 0.01380694421340037871738705044 | 0.3235294117647058823529411765 | 1 |
| DECREASED | 20d | 34 | 0.005735415952244099949280835632 | 0.0048988618517879956325444260 | 0.02697380117039939559548641988 | 0.5882352941176470588235294118 | 1 |
| UNCHANGED | 1d | 2887 | 0.00002192758248782474553888448563 | -0.00004116462970357350150456720 | 0.005516730579577344350647470513 | 0.4960166262556286802909594735 | 0 |
| UNCHANGED | 5d | 2883 | 0.0001247361982236037351016689448 | 0.0000196737308476230198389900 | 0.01208610654552427393115404624 | 0.5005202913631633714880332986 | 4 |
| UNCHANGED | 20d | 2868 | -0.0001161946324118768128337856803 | 0.0007640302896235082348630110 | 0.02373739622098762487042174377 | 0.5146443514644351464435146444 | 19 |

**Primary contrast: mean(INCREASED) - mean(DECREASED)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 25 | 34 | 9 | 10 | 0.002219345477916837005417238659 | [-0.0006589881848375503850018356347, 0.004887620038168901207238878067] | 0.0638 |  |
| 5d | 25 | 34 | 9 | 10 | 0.000753060661389137013809727244 | [-0.005231264081278333109047915304, 0.005905309467657393453594436012] | 0.4075 |  |
| 20d | 25 | 34 | 9 | 10 | -0.001132732993330299921997441900 | [-0.01045552658552327626990573198, 0.008028251293483593434945934277] | 0.5843 |  |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| INCREASED | 1d | -0.001658003697890860977249432938 n=8 (sparse) | 0.0012888723798475123191673652 n=2 (sparse) | 0.001662848340729112228683252447 n=15 |
| INCREASED | 5d | -0.002818660317047056984335427312 n=8 (sparse) | -0.0066605671256060352483557175 n=2 (sparse) | 0.0008215999426976319222111041933 n=15 |
| INCREASED | 20d | -0.002265921470652554160040250338 n=8 (sparse) | 0.0099308542890300773394084382 n=2 (sparse) | 0.007555515810667018618905997973 n=15 |
| DECREASED | 1d | -0.003323476328315971669287338686 n=14 | -0.0005627397120886594395087011889 n=9 (sparse) | -0.0004068783139040331197986644727 n=11 |
| DECREASED | 5d | -0.006153673146170464531075951407 n=14 | -0.003201311861276781204274821789 n=9 (sparse) | 0.005212367300959833741092319482 n=11 |
| DECREASED | 20d | -0.0006057276811229342432416994 n=14 | 0.003723456677092622487841378878 n=9 (sparse) | 0.01545211089256244320821452665 n=11 |
| UNCHANGED | 1d | 0.00002671913521525468027903681681 n=809 | -0.0001898673382624877363192246889 n=774 | 0.0001446675383959927238773762423 n=1304 |
| UNCHANGED | 5d | 0.00003933190197487274851883219048 n=809 | -0.0008637023909595610810533950491 n=774 | 0.0007663850779874444549859262013 n=1300 |
| UNCHANGED | 20d | -0.0007775551736881000611535519308 n=809 | -0.003024976088784606693173616903 n=774 | 0.002052239239280697144577669831 n=1285 |

### EFFECTIVE / LEVEL

Total attempted observations: 1134

| Disposition | Count |
|---|---|
| BLOCKED | 195 |
| UNAVAILABLE | 939 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 195 |
| UNAVAILABLE | no_effective_state_established | 939 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| POSITIVE | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| POSITIVE | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| POSITIVE | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(POSITIVE) - mean(NEGATIVE)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 5d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 20d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| POSITIVE | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

### EFFECTIVE / CHANGE

Total attempted observations: 5701

| Disposition | Count |
|---|---|
| BLOCKED | 974 |
| UNAVAILABLE | 4727 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | provisional_timing | 974 |
| UNAVAILABLE | no_effective_state_established | 4727 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| INCREASED | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| INCREASED | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| INCREASED | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| DECREASED | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| DECREASED | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| DECREASED | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| UNCHANGED | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| UNCHANGED | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| UNCHANGED | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(INCREASED) - mean(DECREASED)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 5d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 20d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| INCREASED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| INCREASED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| INCREASED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| DECREASED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| DECREASED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| DECREASED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| UNCHANGED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| UNCHANGED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| UNCHANGED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

## USD_CAD

### ANNOUNCED / LEVEL

Total attempted observations: 1134

| Disposition | Count |
|---|---|
| BLOCKED | 707 |
| USABLE | 427 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | missing_baseline | 169 |
| BLOCKED | provisional_timing | 538 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| POSITIVE | 1d | 350 | 0.00002328100917394581202407365629 | 0.0002631824730419499389611645 | 0.004268880347516240834901530140 | 0.5142857142857142857142857143 | 0 |
| POSITIVE | 5d | 349 | 0.00003491805637551397167005890258 | 0.0002394785998238911219756620 | 0.008108261058947377492291975390 | 0.5157593123209169054441260745 | 1 |
| POSITIVE | 20d | 346 | 0.0003243705901149518880078493844 | 0.0016951021760907892404018095 | 0.01589158356952912512947751921 | 0.5231213872832369942196531792 | 4 |
| NEGATIVE | 1d | 77 | -0.0006641036940455575990411701948 | 0.0000606570676857054037865170 | 0.005912215193316156195063881960 | 0.5064935064935064935064935065 | 0 |
| NEGATIVE | 5d | 77 | 0.0003064407315367454560592963416 | 0.0006736610030659230878170700 | 0.01223034327503016749168561283 | 0.5324675324675324675324675325 | 0 |
| NEGATIVE | 20d | 77 | 0.0001383913993673416149986497390 | 0.0010052088092844740930275060 | 0.02558884829791142195672547177 | 0.5064935064935064935064935065 | 0 |
| ZERO | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(POSITIVE) - mean(NEGATIVE)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 350 | 77 | 9 | 6 | 0.0006873847032195034110652438511 | [-0.001216969598400068371109527671, 0.001376095439194008075862768732] | 0.2091 |  |
| 5d | 349 | 77 | 9 | 6 | -0.0002715226751612314843892374450 | [-0.005706029733698145434949976756, 0.001151478603745393366093977585] | 0.6316 |  |
| 20d | 346 | 77 | 9 | 6 | 0.0001859791907476102730091996555 | [-0.02669684558243634161036830950, 0.007909821805895600686160951131] | 0.4901 |  |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| POSITIVE | 1d | n/a n=0 (sparse) | -0.0004314341850921248354093387472 n=106 | 0.0002208212165190420768926872414 n=244 |
| POSITIVE | 5d | n/a n=0 (sparse) | 0.00002594229063020483209091421415 n=106 | 0.00003883341098046363749470637119 n=243 |
| POSITIVE | 20d | n/a n=0 (sparse) | 0.00009646754024265068368095098396 n=106 | 0.0004250277704752182532522295258 n=240 |
| NEGATIVE | 1d | n/a n=0 (sparse) | -0.001116928614710791903698805283 n=52 | 0.000277772140938129754646710788 n=25 |
| NEGATIVE | 5d | n/a n=0 (sparse) | -0.0005279314693226948292016201308 n=52 | 0.002041934909324381249402002604 n=25 |
| NEGATIVE | 20d | n/a n=0 (sparse) | -0.004001476494300964462649116962 n=52 | 0.008749316618197418256506004476 n=25 |
| ZERO | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

### ANNOUNCED / CHANGE

Total attempted observations: 5701

| Disposition | Count |
|---|---|
| BLOCKED | 3582 |
| GAP | 2 |
| NO_ENTRY_AVAILABLE | 1 |
| USABLE | 2116 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | missing_baseline | 833 |
| BLOCKED | provisional_timing | 2749 |
| GAP | transition_unknown_due_to_gap | 2 |
| NO_ENTRY_AVAILABLE | no D-bar available strictly after as_of | 1 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| INCREASED | 1d | 23 | -0.0002744727828863099488799232348 | 0.0013424664473850852339546310 | 0.006266665311209996564420792849 | 0.6956521739130434782608695652 | 1 |
| INCREASED | 5d | 23 | -0.00002949318877548127063357008261 | -0.00028546541842642677812017360 | 0.009805714136351494674805241211 | 0.4782608695652173913043478261 | 1 |
| INCREASED | 20d | 23 | -0.006943963737909004884685868743 | -0.00643083253609724925847809790 | 0.01734916676770606423939496305 | 0.4347826086956521739130434783 | 1 |
| DECREASED | 1d | 19 | -0.001120307620013669586022700168 | -0.00119582548195390636324104940 | 0.002702947523438430214188840041 | 0.3684210526315789473684210526 | 0 |
| DECREASED | 5d | 19 | -0.0005579837438299234488667342737 | 0.0002323622527520404310319790 | 0.007021812205424208561624643045 | 0.5789473684210526315789473684 | 0 |
| DECREASED | 20d | 19 | 0.006114617619350137922193142863 | 0.0067198538221422589447785890 | 0.01206489708975888074011788721 | 0.7368421052631578947368421053 | 0 |
| UNCHANGED | 1d | 2073 | 0.00001581002522589841772788991027 | 0.0001967488185790280608362200 | 0.004042632259697849638607222147 | 0.5238784370477568740955137482 | 0 |
| UNCHANGED | 5d | 2069 | 0.00004948248914167546624081498695 | 0.0002078886310904872389791180 | 0.009027513936912898634308343903 | 0.5103914934751087481875302078 | 4 |
| UNCHANGED | 20d | 2054 | 0.0002863565582937979042456679907 | 0.0014176532905949097417240380 | 0.01792641043718966898749564187 | 0.5321324245374878286270691334 | 19 |

**Primary contrast: mean(INCREASED) - mean(DECREASED)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 23 | 19 | 7 | 7 | 0.0008458348371273596371427769332 | [-0.0008779439358943213899559171140, 0.002280053457954145170340537974] | 0.1631 |  |
| 5d | 23 | 19 | 7 | 7 | 0.0005284905550544421782331641911 | [-0.003650047177548094998238569890, 0.004671016739208409366434992530] | 0.3999 |  |
| 20d | 23 | 19 | 7 | 7 | -0.01305858135725914280687901161 | [-0.02201893503114056966450084071, -0.006714672096216950678623611758] | 1 |  |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| INCREASED | 1d | n/a n=0 (sparse) | -0.0000573821895839780870597335375 n=8 (sparse) | -0.00039025443264755360851735774 n=15 |
| INCREASED | 5d | n/a n=0 (sparse) | 0.002423944914037420421825465988 n=8 (sparse) | -0.001337993510275695506611722653 n=15 |
| INCREASED | 20d | n/a n=0 (sparse) | -0.01386689568107673686519347546 n=8 (sparse) | -0.00325173336821954782841514516 n=15 |
| DECREASED | 1d | n/a n=0 (sparse) | -0.00010308155110831716006221956 n=5 (sparse) | -0.001483602644622724023865728957 n=14 |
| DECREASED | 5d | n/a n=0 (sparse) | -0.0042107544297271378774465788 n=5 (sparse) | 0.0007465772154190817041974959143 n=14 |
| DECREASED | 20d | n/a n=0 (sparse) | 0.0100317856432033872195187066 n=5 (sparse) | 0.004715629039402548887434012957 n=14 |
| UNCHANGED | 1d | n/a n=0 (sparse) | -0.00001941000315652407505190032124 n=772 | 0.00003670922730985703757877235911 n=1301 |
| UNCHANGED | 5d | n/a n=0 (sparse) | -0.0001697985058562907245032299325 n=772 | 0.0001800028655012975936536158184 n=1297 |
| UNCHANGED | 20d | n/a n=0 (sparse) | -0.001149554865163512584918032390 n=772 | 0.001151039568363254766674979027 n=1282 |

### EFFECTIVE / LEVEL

Total attempted observations: 1134

| Disposition | Count |
|---|---|
| BLOCKED | 363 |
| UNAVAILABLE | 771 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | missing_baseline | 169 |
| BLOCKED | provisional_timing | 194 |
| UNAVAILABLE | no_effective_state_established | 771 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| POSITIVE | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| POSITIVE | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| POSITIVE | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| NEGATIVE | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| ZERO | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(POSITIVE) - mean(NEGATIVE)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 5d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 20d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| POSITIVE | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| POSITIVE | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| NEGATIVE | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| ZERO | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

### EFFECTIVE / CHANGE

Total attempted observations: 5701

| Disposition | Count |
|---|---|
| BLOCKED | 1801 |
| UNAVAILABLE | 3900 |

| Disposition | Reason | Count |
|---|---|---|
| BLOCKED | missing_baseline | 833 |
| BLOCKED | provisional_timing | 968 |
| UNAVAILABLE | no_effective_state_established | 3900 |

| Group | Horizon | n | mean | median | stdev | positive_frac | censored |
|---|---|---|---|---|---|---|---|
| INCREASED | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| INCREASED | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| INCREASED | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| DECREASED | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| DECREASED | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| DECREASED | 20d | 0 | n/a | n/a | n/a | n/a | 0 |
| UNCHANGED | 1d | 0 | n/a | n/a | n/a | n/a | 0 |
| UNCHANGED | 5d | 0 | n/a | n/a | n/a | n/a | 0 |
| UNCHANGED | 20d | 0 | n/a | n/a | n/a | n/a | 0 |

**Primary contrast: mean(INCREASED) - mean(DECREASED)** (deterministic calendar-year cluster bootstrap, 95% CI, seed=46, resamples=10000)

| Horizon | n_a | n_b | years_a | years_b | diff | 95% CI | frac<=0 | note |
|---|---|---|---|---|---|---|---|---|
| 1d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 5d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |
| 20d | 0 | 0 | 0 | 0 | n/a | n/a | n/a | not computable: one or both groups have zero usable observations at this horizon |

Time stability by era (mean return, count; "sparse" if n<10):

| Group | Horizon | 2005-2011 | 2012-2018 | 2019-cutoff |
|---|---|---|---|---|
| INCREASED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| INCREASED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| INCREASED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| DECREASED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| DECREASED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| DECREASED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| UNCHANGED | 1d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| UNCHANGED | 5d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |
| UNCHANGED | 20d | n/a n=0 (sparse) | n/a n=0 (sparse) | n/a n=0 (sparse) |

## Secondary: equal-pair-weighted pooled summary (NOT primary)

Simple unweighted mean of the 3 pairs' own observed contrast point estimates -- each pair counted once regardless of sample size. No pooled confidence interval is computed here; the per-pair results above, each with its own proper cluster-bootstrap CI, are the primary, authoritative results.

| Semantics | Experiment | Horizon | Pairs contributing | Equal-weighted mean diff |
|---|---|---|---|---|
| ANNOUNCED | LEVEL | 1d | 3/3 | 0.0001577622392761211955628322649 |
| ANNOUNCED | LEVEL | 5d | 3/3 | -0.004280069872571709382914779633 |
| ANNOUNCED | LEVEL | 20d | 3/3 | -0.01984731428598862809375800165 |
| ANNOUNCED | CHANGE | 1d | 3/3 | 0.0002487574962784959012259001997 |
| ANNOUNCED | CHANGE | 5d | 3/3 | -0.001047714997036796887135026290 |
| ANNOUNCED | CHANGE | 20d | 3/3 | -0.005481090147143268518504409983 |
| EFFECTIVE | LEVEL | 1d | 0/3 | n/a |
| EFFECTIVE | LEVEL | 5d | 0/3 | n/a |
| EFFECTIVE | LEVEL | 20d | 0/3 | n/a |
| EFFECTIVE | CHANGE | 1d | 1/3 | 0.0004963762323071178791924419106 |
| EFFECTIVE | CHANGE | 5d | 1/3 | -0.001857297027478850026148699678 |
| EFFECTIVE | CHANGE | 20d | 1/3 | -0.003720659855137637220930380472 |

## Limitations

- Statistical association is not economic magnitude, temporal stability, sample coverage, or tradability -- each is a separate question this report does not collapse into a single verdict. Tradability (spread, slippage, financing, execution) is explicitly out of scope.
- A CI crossing zero means this data cannot distinguish the contrast from noise at this horizon/pair/semantics -- it does not mean the feature is proven useless.
- A positive point estimate or a CI excluding zero is evidence of association in the tested sample -- not proof of alpha, profitability, or causation.
- EFFECTIVE-semantics coverage is smaller than ANNOUNCED by construction (FX-45/FX-45H): GBP and CAD currently have no verified effective-date coverage at all, so EFFECTIVE results for any pair involving them are UNAVAILABLE for the whole history, not a weak or noisy result -- see disposition counts above.
- No imputation, no EFFECTIVE->ANNOUNCED fallback, and no post-hoc changes to instruments, horizons, eras, or grouping were made after this script was run against real data.
- 10,000-resample bootstraps drawn from a small number of distinct calendar-year clusters (see each contrast's own n_years_a/n_years_b and the era table's own per-era counts) are not 10,000 independent historical years -- interpret CI width accordingly, the same caveat this project's own FX-39 bootstrap work already carries.
- A contrast reporting NOT_ESTIMABLE (see its own note) means the calendar-year cluster bootstrap could not compute a confidence interval at all -- either an arm has fewer than 2 distinct year clusters in the full sample, or the bootstrap's redraw cap was exhausted for a structurally pathological cluster imbalance (FX-46H). This is reported explicitly rather than as a wide-but-computed CI or a fabricated value -- do not read the observed point estimate alone as evidence of association when its own contrast is NOT_ESTIMABLE.
