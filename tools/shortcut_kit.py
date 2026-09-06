"""Primitives for writing Shortcuts action plists by hand.

Every serialization in here is either lifted verbatim from a Shortcut that is known
to work on Tobias's phone, or from a parameter key mined out of WorkflowKit's
Localizable.loctable (the loctable spells action summaries as
"Get contents of ${WFFolder}", which names the real input key). Nothing here is
guessed: a guessed key does not error, it silently leaves the action's input chip
unbound, which is the single most expensive failure mode in this project.

Sources are recorded in KEY_PROVENANCE so tools/verify_shortcuts.py can refuse to
ship an action whose input key nobody has ever seen work.
"""

import plistlib
import uuid as _uuid

TOKEN = '￼'  # the placeholder Shortcuts puts in a string where a token sits


def uid():
    return str(_uuid.uuid4()).upper()


# ── Attachments ─────────────────────────────────────────────
def out(action_uuid, output_name):
    """The output of an earlier action ("magic variable")."""
    return {'Value': {'OutputName': output_name,
                      'OutputUUID': action_uuid,
                      'Type': 'ActionOutput'},
            'WFSerializationType': 'WFTextTokenAttachment'}


def var(name):
    """A named variable set by Set Variable / Add to Variable."""
    return {'Value': {'Type': 'Variable', 'VariableName': name},
            'WFSerializationType': 'WFTextTokenAttachment'}


def shortcut_input():
    """What the shortcut was handed when it was run."""
    return {'Value': {'Type': 'ExtensionInput'},
            'WFSerializationType': 'WFTextTokenAttachment'}


def text(template, *tokens):
    """A text field with tokens in it.

    `template` uses {} for each token, in order. Shortcuts stores the string with
    U+FFFC where a token sits and an attachmentsByRange map keyed by the character
    offset of that placeholder, so the offsets have to be computed after
    substitution, not before.
    """
    if not tokens:
        return template
    parts = template.split('{}')
    assert len(parts) == len(tokens) + 1, f'{len(tokens)} tokens for {len(parts) - 1} slots'
    string, ranges = parts[0], {}
    for token, tail in zip(tokens, parts[1:]):
        ranges['{%d, 1}' % len(string)] = token['Value']
        string += TOKEN + tail
    return {'Value': {'string': string, 'attachmentsByRange': ranges},
            'WFSerializationType': 'WFTextTokenString'}


def album(name):
    """The value shape a Find Photos album filter wants."""
    return {'Enumeration': {'Value': name,
                            'WFSerializationType': 'WFStringSubstitutableState'}}


# ── Actions ─────────────────────────────────────────────────
def action(identifier, **params):
    return {'WFWorkflowActionIdentifier': identifier,
            'WFWorkflowActionParameters': params}


# Which parameter carries each action's input, and where that is known from.
# verify_shortcuts.py checks every action it builds against this table.
KEY_PROVENANCE = {
    'is.workflow.actions.filter.photos':      (None, 'live: Export Triage v7'),
    'is.workflow.actions.setvariable':        ('WFInput', 'live: Export Triage v7'),
    'is.workflow.actions.appendvariable':     ('WFInput', 'live: Delete Photos By Index'),
    'is.workflow.actions.count':              ('Input', 'live: Export Triage v7'),
    'is.workflow.actions.repeat.count':       (None, 'live: Export Triage v7'),
    'is.workflow.actions.repeat.each':        ('WFInput', 'live: Delete Photos By Index'),
    'is.workflow.actions.conditional':        ('WFInput', 'loctable + shortcuts-toolkit'),
    'is.workflow.actions.getitemfromlist':    ('WFInput', 'live: Export Triage v7'),
    'is.workflow.actions.getitemname':        ('WFInput', 'loctable: Get name of ${WFInput}'),
    'is.workflow.actions.image.resize':       ('WFImage', 'live: Export Triage v7'),
    'is.workflow.actions.image.convert':      ('WFInput', 'live: Export Triage v7'),
    'is.workflow.actions.encodemedia':        ('WFMedia', 'loctable: Encode ${WFMedia}'),
    'is.workflow.actions.documentpicker.save': ('WFInput', 'live: Export Triage v7'),
    'is.workflow.actions.setitemname':        ('WFInput', 'live: Export Triage v7'),
    'is.workflow.actions.gettext':            (None, 'live: Export Triage v7'),
    'is.workflow.actions.text.combine':       ('text', 'same family as text.split (live)'),
    'is.workflow.actions.text.split':         ('text', 'live: Delete Photos By Index'),
    'is.workflow.actions.date':               (None, 'live: Export Triage v7'),
    'is.workflow.actions.savetocameraroll':   ('WFInput', 'live: Refresh Triage'),
    'is.workflow.actions.removefromalbum':    ('WFInput', 'loctable: Remove ${WFInput} from ${WFRemoveAlbumSelectedGroup}'),
    'is.workflow.actions.deletephotos':       ('photos', 'live: Delete Photos By Index'),
    'is.workflow.actions.previewdocument':    ('WFInput', 'loctable: Show ${WFInput} in Quick Look'),
    'is.workflow.actions.showresult':         (None, 'live: Delete Photos By Index'),
    'is.workflow.actions.notification':       (None, 'loctable: Show notification ${WFNotificationActionBody}'),
    'is.workflow.actions.format.date':        ('WFDate', 'loctable: Date (WFDate)'),
    'is.workflow.actions.number':             (None, 'loctable: ${WFNumberActionNumber}'),
    'is.workflow.actions.getlastscreenshot':  (None, 'loctable: Get the latest ${WFGetLatestPhotoCount}'),
}


# ── Building blocks used by more than one shortcut ──────────
def find_photos(u, filters, sort='Date Taken', order='Oldest First', limit=None):
    p = {'UUID': u,
         'WFContentItemSortProperty': sort,
         'WFContentItemSortOrder': order,
         'WFContentItemLimitEnabled': limit is not None}
    if limit is not None:
        p['WFContentItemLimitNumber'] = float(limit)
    if filters:
        p['WFContentItemFilter'] = {
            'Value': {'WFActionParameterFilterPrefix': 1,   # 1 = all of the following
                      'WFActionParameterFilterTemplates': filters,
                      'WFContentPredicateBoundedDate': False},
            'WFSerializationType': 'WFContentPredicateTableTemplate'}
    return action('is.workflow.actions.filter.photos', **p)


def album_is(name):
    # Operator 4 = "is", verified against both live shortcuts.
    return {'Operator': 4, 'Property': 'Album', 'Removable': True, 'Values': album(name)}


def taken_within_days(n):
    # Operator 1001 = relative date, Unit 16 = days. Verified against Refresh Triage,
    # which uses the same shape on Last Modified Date.
    return {'Operator': 1001, 'Property': 'Date Taken', 'Removable': True,
            'Values': {'Number': str(n), 'Unit': 16}}


def set_var(name, value):
    return action('is.workflow.actions.setvariable', WFVariableName=name, WFInput=value)


def append_var(name, value):
    return action('is.workflow.actions.appendvariable', WFVariableName=name, WFInput=value)


def repeat_each(over, body):
    g = uid()
    return ([action('is.workflow.actions.repeat.each', GroupingIdentifier=g,
                    WFControlFlowMode=0, WFInput=over)]
            + body
            + [action('is.workflow.actions.repeat.each', GroupingIdentifier=g,
                      WFControlFlowMode=2)])


def repeat_count(n, body):
    g = uid()
    return ([action('is.workflow.actions.repeat.count', GroupingIdentifier=g,
                    WFControlFlowMode=0, WFRepeatCount=n)]
            + body
            + [action('is.workflow.actions.repeat.count', GroupingIdentifier=g,
                      WFControlFlowMode=2)])


def if_contains(subject, needle, then, otherwise=None):
    g = uid()
    head = action('is.workflow.actions.conditional', GroupingIdentifier=g,
                  WFControlFlowMode=0, WFInput=subject,
                  WFCondition='Contains', WFConditionalActionString=needle)
    acts = [head] + then
    if otherwise is not None:
        acts.append(action('is.workflow.actions.conditional', GroupingIdentifier=g,
                           WFControlFlowMode=1))
        acts += otherwise
    acts.append(action('is.workflow.actions.conditional', GroupingIdentifier=g,
                       WFControlFlowMode=2))
    return acts


def save_file(name_value, path_value, item):
    """Set Name then Save File.

    The extension of the written file comes from the item's *name*, not from the
    destination path, so both have to carry it and they have to agree.
    """
    named = uid()
    return [action('is.workflow.actions.setitemname', UUID=named, WFInput=item,
                   WFName=name_value, WFDontIncludeFileExtension=True),
            action('is.workflow.actions.documentpicker.save',
                   UUID=uid(), WFAskWhereToSave=False, WFSaveFileOverwrite=True,
                   WFInput=out(named, 'Renamed Item'), WFFileDestinationPath=path_value)]


# ── Output ──────────────────────────────────────────────────
def write_shortcut(path, actions, *, types=None, input_classes=None):
    wf = {'WFWorkflowActions': actions,
          'WFWorkflowClientVersion': '2038.0.4.4',
          'WFWorkflowHasOutputFallback': False,
          'WFWorkflowHasShortcutInputVariables': any(
              _uses_shortcut_input(a) for a in actions),
          'WFWorkflowIcon': {'WFWorkflowIconGlyphNumber': 59511,
                             'WFWorkflowIconStartColor': 4282601983},
          'WFWorkflowImportQuestions': [],
          'WFWorkflowInputContentItemClasses': input_classes or [
              'WFAppStoreAppContentItem', 'WFArticleContentItem', 'WFContactContentItem',
              'WFDateContentItem', 'WFEmailAddressContentItem', 'WFGenericFileContentItem',
              'WFImageContentItem', 'WFiTunesProductContentItem', 'WFLocationContentItem',
              'WFDCMapsLinkContentItem', 'WFAVAssetContentItem', 'WFPDFContentItem',
              'WFPhoneNumberContentItem', 'WFRichTextContentItem', 'WFSafariWebPageContentItem',
              'WFStringContentItem', 'WFURLContentItem'],
          'WFWorkflowMinimumClientVersion': 900,
          'WFWorkflowMinimumClientVersionString': '900',
          'WFWorkflowOutputContentItemClasses': [],
          'WFWorkflowTypes': types if types is not None else ['NCWidget', 'WatchKit']}
    with open(path, 'wb') as fh:
        plistlib.dump(wf, fh)
    return wf


def _uses_shortcut_input(a):
    def walk(v):
        if isinstance(v, dict):
            if v.get('Type') == 'ExtensionInput':
                return True
            return any(walk(x) for x in v.values())
        if isinstance(v, list):
            return any(walk(x) for x in v)
        return False
    return walk(a.get('WFWorkflowActionParameters', {}))
