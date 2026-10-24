HEADLINE = (
 '{{#with (headline data (variable "__to"))}}<div class="gx"><div class="tiles">'
 '{{#if orchestrator}}{{#with orchestrator}}<div class="tile pick {{kind}}" data-tile="orchestrator"><span class="k">Next orchestrator</span>'
 '<span class="v"><span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span>{{name}}</span><span class="s" title="{{model}}">{{model}}{{#if detail}} · {{detail}}{{/if}}</span></div>{{/with}}'
 '{{else}}<div class="tile pick unk" data-tile="orchestrator"><span class="k">Next orchestrator</span><span class="v">None available</span><span class="s">every orchestrator is out or held</span></div>{{/if}}'
 '{{#if worker}}{{#with worker}}<div class="tile pick {{kind}}" data-tile="worker"><span class="k">Next worker</span>'
 '<span class="v"><span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span>{{name}}</span><span class="s" title="{{model}}">{{model}}{{#if detail}} · {{detail}}{{/if}}</span></div>{{/with}}'
 '{{else}}<div class="tile pick unk" data-tile="worker"><span class="k">Next worker</span><span class="v">None available</span><span class="s">every worker route is out or held</span></div>{{/if}}'
 '<div class="tile stat out{{#unless out.count}} zero{{/unless}}" data-tile="out"><span class="k">Out of quota</span><span class="v">{{out.count}}</span><span class="s" title="{{out.text}}">{{#if out.count}}{{out.text}}{{else}}none{{/if}}</span></div>'
 '<div class="tile stat warn{{#unless behind.count}} zero{{/unless}}" data-tile="behind"><span class="k">Behind pace</span><span class="v">{{behind.count}}</span><span class="s" title="{{behind.text}}">{{#if behind.count}}{{behind.text}}{{else}}none{{/if}}</span></div>'
 '<div class="tile stat bad{{#unless over.count}} zero{{/unless}}" data-tile="over"><span class="k">Overspent</span><span class="v">{{over.count}}</span><span class="s" title="{{over.text}}">{{#if over.count}}{{over.text}}{{else}}none{{/if}}</span></div>'
 '<div class="tile stat unk{{#unless unknown.count}} zero{{/unless}}" data-tile="unknown"><span class="k">No reading</span><span class="v">{{unknown.count}}</span><span class="s" title="{{unknown.text}}">{{#if unknown.count}}{{unknown.text}}{{else}}none{{/if}}</span></div>'
 '</div></div>{{/with}}'
)

def lane_section(key, title, sub, limit, empty):
    return (
     '{{#with (laneRows data (variable "__to") "@KEY@" @LIMIT@)}}<div class="ls" data-lane="@KEY@">'
     '<header><b>@TITLE@</b><span>@SUB@</span></header>'
     '{{#if rows.length}}<ol>{{#each rows}}<li class="r {{kind}}{{#if first}} first{{/if}}{{#if next}} next{{/if}}" data-provider="{{provider}}" data-rank="{{rank}}">'
     '<div class="rw"><span class="n">{{rank}}</span><span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span>'
     '<div class="bd"><div class="l1"><b class="nm">{{name}}</b>{{#if next}}<em class="pill good">Next</em>{{/if}}{{#if word}}<em class="pill {{kind}}">{{word}}</em>{{/if}}'
     '<span class="md" title="{{model}}">{{model}}</span>{{#if (eq kind "unk")}}<span class="pa unk"></span>{{/if}}{{#if capacity}}<span class="big {{#if leftText}}{{kind}}{{else}}unk{{/if}}">{{capacity}}</span>{{/if}}</div>'
     '{{#if acctNote}}<div class="l2"><span class="pt">{{acctNote}}</span>{{#if when}}<span class="wn"><span class="sw">{{word}} · </span>{{when}}</span>{{/if}}</div>{{/if}}'
     '{{#if pace}}<div class="l2">{{#if paceLong}}<span class="pa {{#if paKnown}}{{paSide}}{{else}}unk{{/if}}">{{#if paKnown}}<i style="left:{{paLeft}}%;width:{{paWidth}}%"></i>{{/if}}</span>'
     '<span class="pt">{{#if paKnown}}<span class="pv">{{paText}}</span> <span class="long">Paced Availability</span><span class="short">pace</span>{{else}}{{#if out}}<span class="pv unk">no pace while out</span>{{else}}<span class="pv unk">pace unknown</span>{{/if}}{{/if}}</span>{{else}}<span class="pt"></span>{{/if}}'
     '{{#if when}}<span class="wn"><span class="sw">{{word}}{{#if word}} · {{/if}}</span>{{when}}</span>{{/if}}</div>{{/if}}</div></div></li>{{/each}}</ol>'
     '{{#if more}}<div class="more">+ {{more}} more routes on the Free models page</div>{{/if}}'
     '{{else}}<div class="none">@EMPTY@</div>{{/if}}</div>{{/with}}'
    ).replace('@KEY@', key).replace('@LIMIT@', str(limit)).replace('@TITLE@', title).replace('@SUB@', sub).replace('@EMPTY@', empty)

PAID = (
 '<section class="gx"><div class="in prov" data-pool="paid"><header><b>Paid providers</b><span>lowest allowance first · white tick is the on-pace line · hatched means unknown</span></header>'
 '<ol>{{#each (providerRows data (variable "__to"))}}<li class="pr {{kind}}" data-provider="{{account}}">'
 '<div class="t"><span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span><b class="nm">{{name}}</b>{{#if partial}}<em class="pill warn">Partial</em>{{/if}}'
 '<span class="big {{kind}}">{{head}}</span></div>'
 '{{#if bar}}<div class="bar{{#if bar.estimated}} estimated{{/if}}{{#if (eq kind "out")}} out{{/if}}"><div class="fill" style="width:{{bar.width}}%"></div>{{#if bar.tick}}<div class="tick" style="left:calc({{bar.tick}}% - 1px)"></div>{{/if}}</div>'
 '{{else}}<div class="bar {{#if (eq kind "out")}}out{{else}}unk{{/if}}"></div>{{/if}}'
 '<div class="dt">{{detail}}</div>'
 '{{#if chips.length}}<div class="ch">{{#each chips}}<span class="{{kind}}">{{label}} {{text}}</span>{{/each}}</div>{{/if}}'
 '</li>{{/each}}</ol></div></section>'
)

FREE = (
 '<section class="gx"><div class="in frees" data-pool="free"><header><b>Free providers</b><span>owner-approved providers only · blocked first · hatched means no limit seen, not 100% (filled by #467)</span></header>'
 '<ol>{{#each (freeRows data (variable "__to"))}}<li class="fr {{kind}}" data-provider="{{account}}"><div class="r1">'
 '<span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span><span class="nm">{{name}}</span>{{#if models}}<span class="mc">{{models}}</span>{{/if}}'
 '{{#if bar}}<span class="bar fb"><span class="fill" style="width:{{bar.width}}%"></span></span>{{else}}<span class="bar fb {{#if (eq kind "out")}}out{{else}}unk{{/if}}"></span>{{/if}}'
 '<span class="st">{{head}}</span></div>{{#if sub}}<div class="wy">{{sub}}</div>{{/if}}</li>{{/each}}</ol></div></section>'
)


def lane(*sections):
    return '<section class="gx"><div class="in lane">' + ''.join(lane_section(*x) for x in sections) + '</div></section>'
